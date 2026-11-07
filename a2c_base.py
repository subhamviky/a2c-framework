"""a2c_base.py — A2C (Architecture-to-Code) reference classes, built on E2A.

E2A governs how agentic systems are built; A2C uses E2A-governed agents to
generate production-grade service code, Terraform and CI/CD with mandatory
NFRs injected before any model call (A2C Framework Reference).

Requires e2a-framework/reference/e2a_base.py on sys.path (it is the single
source of truth for the E2A classes and is deliberately not copied here).

Classes
  DevRequest                    TypedDict — A2C input/output contract
  GovernanceViolationError      unapproved cloud or agent
  SDLCAssistantAgent(BaseAgent) A2C base agent: NFR injection, cloud check,
                                generation_key; used alone it generates the
                                service code in one call (prototype pattern)
  RequirementsAgent, CodeGenAgent, IaCAgent, CICDAgent
                                specialists (extend SDLCAssistantAgent)
  CodeCriticAgent(BaseAgent)    quality gate: model review AND a deterministic
                                NFR-pattern check of the code (min of both)
  SDLCAgentChain                the workflow node sequence (run() like an agent)
  SDLCWorkflow(BaseWorkflow)    execute(dev_request, config) -> DevRequest
  DevPlatformValidationService  _validate_<agent_name> validators (runs before)
  LocalArtifactWriter           conditional file writes (project + path key)
  CodeGenTool, IaCGenTool, CICDGenTool, TerraformValidateTool
                                BaseToolService subclasses for remote writes

Invariants: run() and execute() are never overridden; no agent defines
_validate_state; every completion goes through config['llm_service']; no
agent keeps its own semaphore, rate limiter or provider SDK; class generation
(G2C) never produces IaC/CI-CD — SDLCWorkflow must be run explicitly.
"""
import hashlib
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from e2a_base import (BaseAgent, BaseToolService, BaseValidationService, BaseWorkflow,
                      ConfigKey, Deadline, NFRViolationError, PhysicalOutcome, ValidationResult,
                      register_config_key, resolve_config)

MANDATORY_NFRS = ['Idempotency', 'Observability', 'CircuitBreaker',
                  'RetryWithBackoff', 'HealthCheck', 'GracefulShutdown']
APPROVED_CLOUDS = ['aws', 'gcp', 'azure', 'standalone']

def _to_bool(v):
    return str(v).strip().lower() in ('1', 'true', 'yes', 'on')


# A2C keys in the central E2A registry (kwargs > config > env > default via
# resolve_config). Code generation is slower and larger than agent calls, so
# A2C passes its own min_confidence / max_latency / max_tokens to each agent.
for _spec in (
    ConfigKey('a2c_min_confidence', 'A2C_MIN_CONFIDENCE', 0.75, float, 'A2C',
              'SDLCAgentChain — agent fallback and CodeCriticAgent threshold'),
    ConfigKey('a2c_max_latency', 'A2C_MAX_LATENCY', 30.0, float, 'A2C',
              'SDLCAgentChain — per-agent latency SLO (seconds)'),
    ConfigKey('a2c_max_tokens', 'A2C_MAX_TOKENS', 32000, int, 'A2C',
              'SDLCAgentChain — per-agent token budget'),
    ConfigKey('a2c_max_regenerations', 'A2C_MAX_REGENERATIONS', 2, int, 'A2C',
              'SDLCAgentChain — business-code regenerations after a failed review'),
    ConfigKey('a2c_sequence', 'A2C_SEQUENCE', 'nfr_first', str, 'A2C',
              "SDLCAgentChain — 'nfr_first' (default) or 'topology'"),
    ConfigKey('a2c_write_artifacts', 'A2C_WRITE_ARTIFACTS', True, _to_bool, 'A2C',
              'SDLCAgentChain — write artifacts into dev_request.project_root'),
    ConfigKey('critic_model_id', 'CRITIC_MODEL_ID', None, str, 'A2C',
              'SDLCAgentChain — model for CodeCriticAgent (cheaper)'),
):
    register_config_key(_spec)

A2C_KEYS = ('a2c_min_confidence', 'a2c_max_latency', 'a2c_max_tokens', 'a2c_max_regenerations',
            'a2c_sequence', 'a2c_write_artifacts', 'critic_model_id')


def a2c_settings(config=None) -> Dict[str, Any]:
    return {k: resolve_config(k, config) for k in A2C_KEYS}

# Code patterns per NFR; matched against code with comments removed, so an
# NFR mentioned only in a comment does not count.
NFR_PATTERNS = {
    'Idempotency': r'idempot|request_id|conditional[_ ]?write|put_if_version|claim\(',
    'Observability': r'structlog|opentelemetry|otel|logging\.getLogger|logger\.',
    'CircuitBreaker': r'circuit|breaker|pybreaker|resilience4j',
    'RetryWithBackoff': r'retry|backoff|tenacity',
    'HealthCheck': r'/health|healthcheck|actuator',
    'GracefulShutdown': r'sigterm|signal\.|graceful|shutdown',
}


class GovernanceViolationError(NFRViolationError):
    """A request outside the approved clouds or agents."""


class DevRequest(TypedDict, total=False):
    # ── Developer / P0 hand-off ─────────────────────────────────────────────
    project_name: str
    project_type: str          # 'FastAPI Microservice' | 'Spring Boot' | 'LangGraph Agent'
    mandatory_nfrs: List[str]  # requested; A2C adds the missing mandatory ones
    context: str
    target_cloud: str          # 'aws' | 'gcp' | 'azure' | 'standalone'
    language: str              # 'python' | 'java'
    tenant_id: str             # required by SDLCWorkflow.execute()
    project_root: str          # P0 workspace; artifacts are written here
    # ── Written by A2C ──────────────────────────────────────────────────────
    generation_key: str        # business key project_name:project_type:target_cloud
    spec: str                  # RequirementsAgent
    generated_observability: str
    generated_nfr_module: str
    generated_code: str        # CodeGenAgent (business logic)
    generated_iac: str         # IaCAgent
    generated_cicd: str        # CICDAgent
    critic_report: Dict[str, Any]
    artifacts: Dict[str, str]  # relative path -> sha256 of what was written
    agent_scores: Dict[str, float]
    status: str
    trace_id: str
    request_id: str
    errors: List[str]


def strip_comments(code: str) -> str:
    code = re.sub(r'(?m)#.*$', '', code or '')
    code = re.sub(r'(?m)//.*$', '', code)
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.S)
    return re.sub(r'(?s)("""|\'\'\').*?\1', '', code)


def nfr_pattern_report(code: str, nfrs: List[str]) -> Dict[str, Any]:
    """Deterministic check: which requested NFRs appear as code."""
    body = strip_comments(code).lower()
    known = [n for n in nfrs if n in NFR_PATTERNS]
    found = [n for n in known if re.search(NFR_PATTERNS[n], body)]
    missing = [n for n in known if n not in found]
    score = (len(found) / len(known)) if known else 1.0
    return {'score': round(score, 4), 'passed': found, 'missing': missing}


def _text(response) -> str:
    if isinstance(response, dict):
        return str(response.get('text') or response.get('response') or '')
    return str(response or '')


def _strip_fences(t: str) -> str:
    t = (t or '').strip()
    if t.startswith('```'):
        t = t.split('\n', 1)[1] if '\n' in t else ''
        if t.rstrip().endswith('```'):
            t = t.rstrip()[:-3]
    return t.strip()


# ═══════════════════════════════════════════════════════════════════ agents
class SDLCAssistantAgent(BaseAgent):
    """A2C base agent. run() is inherited from BaseAgent and never overridden;
    input validation is _validate_sdlc_assistant_agent on the validation
    service. Used alone it generates the service code in one model call."""
    agent_name = 'SDLCAssistantAgent'
    artifact_field = 'generated_code'

    def _apply_policy(self, state, config=None, **kwargs) -> None:
        # 1. inject missing mandatory NFRs
        nfrs = state.setdefault('mandatory_nfrs', [])
        injected = [n for n in MANDATORY_NFRS if n not in nfrs]
        nfrs.extend(injected)
        if injected:
            logging.info(f'[{self.agent_name}] A2C policy injection: {injected}')
        # 2. approved cloud and agent
        cfg = config or {}
        approved = cfg.get('approved_clouds', APPROVED_CLOUDS)
        if str(state.get('target_cloud', '')).lower() not in approved:
            raise GovernanceViolationError(f"Cloud {state.get('target_cloud')} not approved")
        agents = cfg.get('approved_agents')
        if agents is not None and self.agent_name not in agents:
            raise GovernanceViolationError(f'{self.agent_name} is not an approved agent')
        # 3. business dedup key (the technical key is the workflow's claim)
        state['generation_key'] = (f"{state.get('project_name')}:{state.get('project_type')}"
                                   f":{state.get('target_cloud')}")

    def _system_prompt(self, state) -> str:
        lang, cloud = state.get('language', 'python'), state.get('target_cloud', 'aws')
        return (f'You are a Principal Cloud Architect generating production-ready {lang} code. '
                f'Generate a {state.get("project_type")} named {state.get("project_name")} for {cloud}. '
                'Mandatory architecture requirements:\n'
                '1. Clean Architecture: data model, interface contract, service layer, exposure layer.\n'
                f'2. All NFRs structurally implemented: {", ".join(state.get("mandatory_nfrs", []))}.\n'
                '3. NFRs appear as code (decorators, middleware, classes), not as comments.\n'
                '4. Structured JSON logging, OpenTelemetry tracing, a /health endpoint.\n'
                '5. E2A template method: one public entry point, protected domain methods, '
                'private infrastructure helpers.\n'
                '6. Model calls only through the injected llm_service; no semaphore, rate limiter '
                'or provider SDK.\nReturn only source code.')

    def _build_messages(self, state, config=None, **kwargs) -> list:
        user = f'Project context: {state.get("context") or "standard microservice"}'
        if state.get('spec'):
            user += f'\n\nSpecification:\n{state["spec"]}'
        if state.get('regeneration_feedback'):
            user += f'\n\nThe previous version failed review; fix: {state["regeneration_feedback"]}'
        return [{'role': 'system', 'content': self._system_prompt(state)},
                {'role': 'user', 'content': user}]

    def _evaluate_output(self, response, state, config=None, **kwargs) -> float:
        text = _strip_fences(_text(response))
        state[self.artifact_field] = text
        report = nfr_pattern_report(text, state.get('mandatory_nfrs', MANDATORY_NFRS))
        state['nfr_check_detail'] = report
        state.setdefault('agent_scores', {})[self.agent_name] = report['score']
        return report['score']

    def _fallback(self, state, config=None, **kwargs):
        missing = (state.get('nfr_check_detail') or {}).get('missing', [])
        return {'text': state.get(self.artifact_field, ''), 'degraded': True,
                'note': f'quality gate below threshold; missing NFR patterns: {missing}'}

    def _handle_error(self, error, state, config=None, **kwargs):
        logging.error(f'[{self.agent_name}][{state.get("project_name", "?")}] {error}')
        state.setdefault('errors', []).append(f'{self.agent_name}: {error}')
        return state


class RequirementsAgent(SDLCAssistantAgent):
    agent_name = 'RequirementsAgent'
    artifact_field = 'spec'

    def _system_prompt(self, state) -> str:
        return ('You are a requirements architect. Produce the project specification: the '
                'TypedDict/DTO schema, the NFR list with the enforcing mechanism for each, the '
                'Clean Architecture layer map and the E2A class mapping. Return Markdown.')

    def _evaluate_output(self, response, state, config=None, **kwargs) -> float:
        text = _strip_fences(_text(response))
        state['spec'] = text
        checks = [bool(text), all(n.lower() in text.lower() for n in state.get('mandatory_nfrs', [])),
                  bool(re.search(r'layer|architecture', text, re.I))]
        score = sum(checks) / len(checks)
        state.setdefault('agent_scores', {})[self.agent_name] = score
        return score


class CodeGenAgent(SDLCAssistantAgent):
    """Three NFR-first modes: observability module, NFR module, business logic."""
    agent_name = 'CodeGenAgent'
    MODES = {'observability': ('generated_observability', ['Observability'],
                               'Generate ONLY the observability module: structured JSON logging, '
                               'OpenTelemetry tracing, metrics and an SLO checker.'),
             'nfr': ('generated_nfr_module', ['CircuitBreaker', 'RetryWithBackoff', 'Idempotency'],
                     'Generate ONLY the NFR module: circuit breakers per dependency, retry with '
                     'jittered backoff, idempotency claim helpers, policy-as-code loading.'),
             'business': ('generated_code', None, 'Generate the business-logic service on top of '
                          'the observability and NFR modules.')}

    def _mode(self, state):
        return self.MODES.get(state.get('codegen_mode') or 'business', self.MODES['business'])

    def _system_prompt(self, state) -> str:
        return super()._system_prompt(state) + '\n' + self._mode(state)[2]

    def _evaluate_output(self, response, state, config=None, **kwargs) -> float:
        field, nfrs, _ = self._mode(state)
        text = _strip_fences(_text(response))
        state[field] = text
        report = nfr_pattern_report(text, nfrs or state.get('mandatory_nfrs', MANDATORY_NFRS))
        state['nfr_check_detail'] = report
        state.setdefault('agent_scores', {})[f'{self.agent_name}:{state.get("codegen_mode") or "business"}'] = report['score']
        return report['score']


class IaCAgent(SDLCAssistantAgent):
    agent_name = 'IaCAgent'
    artifact_field = 'generated_iac'

    def _system_prompt(self, state) -> str:
        return (f'You are a cloud infrastructure engineer. Generate Terraform for '
                f'{state.get("project_name")} on {state.get("target_cloud")}: container compute, '
                'load balancer, queue with a dead-letter queue, secrets, network. Variables for '
                'environment-specific values; no secrets in code. Return only HCL.')

    def _evaluate_output(self, response, state, config=None, **kwargs) -> float:
        text = _strip_fences(_text(response))
        state['generated_iac'] = text
        checks = [len(text) > 100, bool(re.search(r'\b(resource|module)\s+"', text)),
                  bool(re.search(r'dlq|dead[_-]?letter|redrive', text, re.I)),
                  not re.search(r'(?i)(secret|password)\s*=\s*"[^"$]{4,}"', text)]
        score = sum(checks) / len(checks)
        state.setdefault('agent_scores', {})[self.agent_name] = score
        return score


class CICDAgent(SDLCAssistantAgent):
    agent_name = 'CICDAgent'
    artifact_field = 'generated_cicd'

    def _system_prompt(self, state) -> str:
        return ('You are a CI/CD engineer. Generate a GitHub Actions workflow: OIDC cloud auth '
                '(id-token: write), build, tests, evaluation gate, image scan (Trivy), deploy and '
                'automatic rollback. Return only YAML.')

    def _evaluate_output(self, response, state, config=None, **kwargs) -> float:
        text = _strip_fences(_text(response))
        state['generated_cicd'] = text
        checks = [bool(re.search(r'(?m)^on:', text)), 'jobs:' in text,
                  'id-token: write' in text, bool(re.search(r'deploy', text, re.I)),
                  bool(re.search(r'trivy|scan', text, re.I))]
        score = sum(checks) / len(checks)
        state.setdefault('agent_scores', {})[self.agent_name] = score
        return score


class CodeCriticAgent(BaseAgent):
    """Quality gate for generated code. The model reviews the code against
    the mandatory NFRs; the deterministic pattern check runs on the same code
    with comments removed. The reported score is the lower of the two, so a
    lenient review cannot pass code whose NFRs exist only in comments.
    Validation: _validate_code_critic_agent on the validation service."""
    agent_name = 'CodeCriticAgent'

    def _apply_policy(self, state, config=None, **kwargs) -> None:
        """Governance only; the cheaper critic model is chosen by the chain
        (model_id=critic_model_id on this agent's run)."""
        agents = (config or {}).get('approved_agents')
        if agents is not None and self.agent_name not in agents:
            raise GovernanceViolationError(f'{self.agent_name} is not an approved agent')

    def _build_messages(self, state, config=None, **kwargs) -> list:
        code = '\n\n'.join(state.get(k, '') for k in
                           ('generated_observability', 'generated_nfr_module', 'generated_code'))
        return [{'role': 'system', 'content':
                 'You are a senior architect. Score 0.0-1.0: does this code contain all required '
                 'NFR patterns as code (not comments) and the Clean Architecture layers? Return '
                 'JSON only: {"score": float, "missing": [..], "passed": [..]}'},
                {'role': 'user', 'content':
                 f'Required NFRs: {", ".join(state.get("mandatory_nfrs", []))}\n\nCode:\n{code}'}]

    def _evaluate_output(self, response, state, config=None, **kwargs) -> float:
        try:
            review = json.loads(_strip_fences(_text(response)) or '{}')
            model_score = float(review.get('score', 0.0))
        except (json.JSONDecodeError, ValueError, TypeError):
            review, model_score = {'parse_error': True}, 0.0
        code = '\n'.join(state.get(k, '') for k in
                         ('generated_observability', 'generated_nfr_module', 'generated_code'))
        pattern = nfr_pattern_report(code, state.get('mandatory_nfrs', MANDATORY_NFRS))
        score = round(min(model_score, pattern['score']), 4)
        state['critic_report'] = {'score': score, 'model_score': model_score,
                                  'pattern_check': pattern,
                                  'missing': sorted(set(review.get('missing', [])) | set(pattern['missing'])),
                                  'passed': pattern['passed']}
        return score

    def _fallback(self, state, config=None, **kwargs):
        return {'text': 'Code review failed. Regenerating with stricter NFR prompt.', 'degraded': True}

    def _handle_error(self, error, state, config=None, **kwargs):
        logging.error(f'[CodeCriticAgent] {error}')
        state.setdefault('errors', []).append(f'CodeCriticAgent: {error}')
        return state


# ═══════════════════════════════════════════════════════════════ artifacts
class LocalArtifactWriter:
    """Writes generated artifacts into the project workspace. Idempotency key:
    project + relative path. A write is conditional on the content hash read
    at the start of the run: if another writer changed the file meanwhile the
    write is a typed CONFLICT, never a silent overwrite."""
    _locks: Dict[str, threading.Lock] = {}
    _guard = threading.Lock()

    @classmethod
    def _lock(cls, path: str) -> threading.Lock:
        with cls._guard:
            return cls._locks.setdefault(path, threading.Lock())

    @staticmethod
    def read_version(root: str, rel: str) -> Optional[str]:
        p = Path(root) / rel
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None

    def write(self, root: str, rel: str, content: str, expected_version: Optional[str]) -> Dict[str, Any]:
        p = Path(root) / rel
        data = content if content.endswith('\n') else content + '\n'
        new = hashlib.sha256(data.encode()).hexdigest()
        with self._lock(str(p.resolve())):
            current = self.read_version(root, rel)
            if current == new:
                return {'status': 'UNCHANGED', 'path': rel, 'version': new}
            if current != expected_version:
                return {'status': 'CONFLICT', 'path': rel, 'current_version': current}
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(data, encoding='utf-8')
            return {'status': 'COMMITTED', 'path': rel, 'version': new}


_EXT = {'python': 'py', 'java': 'java', 'node': 'ts', 'go': 'go'}


def artifact_paths(state: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, str]:
    ext = _EXT.get(state.get('language', 'python'), 'txt')
    paths = {'spec': 'docs/a2c/spec.md',
             'generated_observability': f'src/generated/observability.{ext}',
             'generated_nfr_module': f'src/generated/nfr.{ext}',
             'generated_code': f'src/generated/service.{ext}',
             'generated_iac': 'infra/main.tf',
             'generated_cicd': '.github/workflows/a2c-ci.yml'}
    paths.update((config or {}).get('a2c_artifact_paths') or {})
    return paths


# ═══════════════════════════════════════════════════════════════ workflow
NFR_FIRST = [('RequirementsAgent', None), ('IaCAgent', None), ('CodeGenAgent', 'observability'),
             ('CICDAgent', None), ('CodeGenAgent', 'nfr'), ('CodeGenAgent', 'business'),
             ('CodeCriticAgent', None)]
TOPOLOGY = [('RequirementsAgent', None), ('CodeGenAgent', 'business'), ('IaCAgent', None),
            ('CICDAgent', None), ('CodeCriticAgent', None)]


class SDLCAgentChain:
    """The workflow's node sequence, run as one unit by BaseWorkflow.execute()
    (it exposes run() with the agent signature). Order is NFR-first by default
    (config['a2c_sequence']='nfr_first'); 'topology' runs the five agents once
    each. Regenerates business code with the critic's findings while the score
    is below threshold (≤ a2c_max_regenerations). Writes artifacts only after
    the critic passes. Stops at the next step boundary when the deadline
    expires or an agent records an error."""

    def __init__(self, agents: Dict[str, BaseAgent], writer: LocalArtifactWriter = None):
        self.agents, self.writer = agents, writer or LocalArtifactWriter()

    def run(self, state, config=None, **kw):
        config = config or {}
        cfg = a2c_settings(config)
        deadline = Deadline.coerce(kw.pop('deadline', None))
        failed_keys = kw.get('failed_keys')
        if failed_keys is None:
            failed_keys = kw['failed_keys'] = []
        base_key = kw.pop('idempotency_key', None) or state.get('generation_key') or 'a2c'
        limits = dict(min_confidence=float(cfg['a2c_min_confidence']),
                      max_latency=float(cfg['a2c_max_latency']),
                      max_tokens=int(cfg['a2c_max_tokens']))
        seq = NFR_FIRST if cfg['a2c_sequence'] == 'nfr_first' else TOPOLOGY
        root = state.get('project_root')
        versions = {}
        if root and cfg['a2c_write_artifacts']:      # version read for conditional writes
            versions = {f: LocalArtifactWriter.read_version(root, rel)
                        for f, rel in artifact_paths(state, config).items()}

        def step(name, mode):
            if deadline:
                deadline.check(f'{name}')
            state['codegen_mode'] = mode
            before = len(state.get('errors', []))
            extra = {'model_id': cfg['critic_model_id']} if (
                name == 'CodeCriticAgent' and cfg['critic_model_id']) else {}
            out = self.agents[name].run(state, config, idempotency_key=f'{base_key}:{name}:{mode or "-"}',
                                        deadline=deadline, **limits, **extra, **kw)
            return out, len(out.get('errors', [])) > before

        for name, mode in seq:
            state, failed = step(name, mode)
            if failed:
                return self._fail(state, failed_keys, base_key, 'AGENT_FAILED')

        threshold = float(cfg['a2c_min_confidence'])
        regen = 0
        while (state.get('critic_report') or {}).get('score', 0.0) < threshold \
                and regen < int(cfg['a2c_max_regenerations']):
            regen += 1
            state['regeneration_feedback'] = state['critic_report'].get('missing', [])
            for name, mode in (('CodeGenAgent', 'business'), ('CodeCriticAgent', None)):
                state, failed = step(name, mode)
                if failed:
                    return self._fail(state, failed_keys, base_key, 'AGENT_FAILED')
        state.pop('regeneration_feedback', None)
        state.pop('codegen_mode', None)
        state['critic_report']['regenerations'] = regen
        if state['critic_report']['score'] < threshold:
            state.setdefault('errors', []).append(
                f"CodeCriticAgent: score {state['critic_report']['score']} below {threshold} after "
                f"{regen} regenerations; missing {state['critic_report'].get('missing')}")
            return self._fail(state, failed_keys, base_key, 'CRITIC_THRESHOLD_NOT_MET')

        if root and cfg['a2c_write_artifacts']:
            self._write(state, config, root, versions, failed_keys, base_key)
        if not state.get('errors'):
            state['status'] = 'GENERATED'
        state['response'] = self._summary(state)
        return state

    def _write(self, state, config, root, versions, failed_keys, base_key):
        state['artifacts'], committed = {}, 0
        for field, rel in artifact_paths(state, config).items():
            if not state.get(field):
                continue
            r = self.writer.write(root, rel, state[field], versions.get(field))
            if r['status'] == 'CONFLICT':
                state.setdefault('errors', []).append(f'artifact conflict: {rel} changed by another writer')
                state['outcome'] = PhysicalOutcome.UNKNOWN.value if committed else None
                state['status'] = 'ARTIFACT_CONFLICT'
                failed_keys.append(base_key)
                return
            committed += r['status'] == 'COMMITTED'
            state['artifacts'][rel] = r['version']
        state['outcome'] = PhysicalOutcome.COMMITTED.value if committed else None

    @staticmethod
    def _fail(state, failed_keys, key, status):
        state['status'] = status
        if key not in failed_keys:
            failed_keys.append(key)
        state['response'] = SDLCAgentChain._summary(state)
        return state

    @staticmethod
    def _summary(state):
        keys = ('generation_key', 'mandatory_nfrs', 'spec', 'generated_observability',
                'generated_nfr_module', 'generated_code', 'generated_iac', 'generated_cicd',
                'critic_report', 'artifacts', 'agent_scores', 'status', 'errors')
        return {k: state[k] for k in keys if k in state}


class SDLCWorkflow(BaseWorkflow):
    """execute(dev_request, config) -> DevRequest (inherited; never overridden).

    BaseWorkflow.execute() supplies the propagation fields, the deadline and
    the atomic idempotency claim on 'a2c:<generation_key>' (tenant-scoped).
    The DevRequest must already have passed DevPlatformValidationService and
    must carry tenant_id. On REPLAY, BaseWorkflow restores only 'response',
    so every artifact is also kept in state['response'] (the run summary)."""

    REQUIRED_NODES = ('RequirementsAgent', 'CodeGenAgent', 'IaCAgent', 'CICDAgent', 'CodeCriticAgent')

    def __init__(self, config: Dict[str, Any] = None, agents: Dict[str, BaseAgent] = None,
                 writer: LocalArtifactWriter = None):
        self.config = config or {}
        self.agents = agents or {'RequirementsAgent': RequirementsAgent(),
                                 'CodeGenAgent': CodeGenAgent(), 'IaCAgent': IaCAgent(),
                                 'CICDAgent': CICDAgent(), 'CodeCriticAgent': CodeCriticAgent()}
        self.writer = writer

    def _build_workflow(self, config=None, **kwargs):
        seq = NFR_FIRST if resolve_config('a2c_sequence', config, kwargs) == 'nfr_first' else TOPOLOGY
        return {'nodes': list(self.agents), 'sequence': seq}

    def _validate_workflow(self, workflow, config=None, **kwargs):
        return all(n in workflow['nodes'] for n in self.REQUIRED_NODES)

    def _get_agent(self, intent, config=None, **kwargs):
        return SDLCAgentChain(self.agents, self.writer)

    def _generate_idempotency_key(self, state, config=None, **kwargs) -> str:
        return (f"a2c:{state.get('project_name')}:{state.get('project_type')}"
                f":{state.get('target_cloud')}")

    def _replayable_result(self, state, config=None, **kwargs) -> Dict[str, Any]:
        return {'response': state.get('response'), 'outcome': state.get('outcome')}

    def _physical_outcome(self, state, config=None, **kwargs):
        o = state.get('outcome')
        return PhysicalOutcome(o) if o else None

    def _handle_error(self, error, state, config=None, **kwargs):
        logging.error(f"[SDLCWorkflow][{state.get('project_name', '?')}] {error}")
        state.setdefault('errors', []).append(f'SDLCWorkflow: {error}')
        return state


# ═══════════════════════════════════════════════════════════════ validation
class DevPlatformValidationService(BaseValidationService):
    """Runs before the workflow (validation tier). One _validate_<agent_name>
    per agent; failure is a ValidationResult, not an exception."""

    def __init__(self, entitlement_policy=None):
        self.entitlement_policy = entitlement_policy
        self.validator_registry = {
            'SDLCAssistantAgent': self._validate_sdlc_assistant_agent,
            'SDLCWorkflow': self._validate_sdlc_assistant_agent,
            'CodeCriticAgent': self._validate_code_critic_agent,
        }

    def _validate_sdlc_assistant_agent(self, state, config=None, **kwargs):
        required = ['project_name', 'project_type', 'mandatory_nfrs', 'target_cloud', 'tenant_id']
        errors = [f'missing field: {k}' for k in required if k not in state]
        if 'mandatory_nfrs' in state and not isinstance(state['mandatory_nfrs'], list):
            errors.append('mandatory_nfrs must be a list')
        return (not errors, errors)

    def _validate_code_critic_agent(self, state, config=None, **kwargs):
        errors = [f'missing field: {k}' for k in ('generated_code', 'mandatory_nfrs') if k not in state]
        return (not errors, errors)

    def _enforce_entitlement_gate(self, agent_name, state, config=None, **kwargs):
        """ABAC hook. Default: allow, unless an entitlement_policy callable
        (agent_name, state, config) -> (bool, reason) denies."""
        cid = state.get('correlation_id')
        if self.entitlement_policy is not None:
            ok, reason = self.entitlement_policy(agent_name, state, config)
            if not ok:
                return ValidationResult(valid=False, errors=[reason], agent_name=agent_name,
                                        correlation_id=cid)
        return ValidationResult(valid=True, errors=[], agent_name=agent_name, correlation_id=cid)


# ═══════════════════════════════════════════════════════════════ tools
class CodeGenTool(BaseToolService):
    """Remote write of a generated file. Idempotency key: project + path."""
    tool_name = 'code_gen'

    def get_endpoint(self, config=None, tenant_id=None, **kwargs):
        return resolve_config('tool_base_url', config, kwargs) + '/codegen/write'

    def _build_payload(self, payload, config=None, **kwargs):
        return {'project_name': payload['project_name'], 'file_path': payload['file_path'],
                'content': payload['content'], 'language': payload.get('language', 'python'),
                'expected_version': payload.get('expected_version'),
                'idempotency_key': f"{payload['project_name']}:{payload['file_path']}"}

    def _validate_input(self, payload, config=None, **kwargs):
        return all(k in payload for k in ('project_name', 'file_path', 'content'))


class IaCGenTool(BaseToolService):
    """Remote write of Terraform. Idempotency key: project + resource_type."""
    tool_name = 'iac_gen'

    def get_endpoint(self, config=None, tenant_id=None, **kwargs):
        return resolve_config('tool_base_url', config, kwargs) + '/iac/write'

    def _build_payload(self, payload, config=None, **kwargs):
        return {**payload, 'idempotency_key': f"{payload.get('project_name')}:{payload.get('resource_type', 'main')}"}

    def _validate_input(self, payload, config=None, **kwargs):
        return 'terraform_hcl' in payload and len(payload['terraform_hcl']) > 100


class CICDGenTool(BaseToolService):
    """Remote write of a workflow. Idempotency key: project + workflow_name."""
    tool_name = 'cicd_gen'

    def get_endpoint(self, config=None, tenant_id=None, **kwargs):
        return resolve_config('tool_base_url', config, kwargs) + '/cicd/write'

    def _build_payload(self, payload, config=None, **kwargs):
        return {**payload, 'idempotency_key': f"{payload.get('project_name')}:{payload.get('workflow_name', 'ci')}"}

    def _validate_input(self, payload, config=None, **kwargs):
        y = payload.get('workflow_yaml', '')
        return 'id-token: write' in y and 'jobs:' in y and bool(re.search(r'deploy', y, re.I))


class TerraformValidateTool(BaseToolService):
    """Read-only `terraform validate` call; no idempotency."""
    tool_name = 'terraform_validate'
    idempotency = False

    def get_endpoint(self, config=None, tenant_id=None, **kwargs):
        return resolve_config('tool_base_url', config, kwargs) + '/terraform/validate'

    def _build_payload(self, payload, config=None, **kwargs):
        return {'terraform_hcl': payload['terraform_hcl']}

    def _validate_input(self, payload, config=None, **kwargs):
        return bool(payload.get('terraform_hcl'))
