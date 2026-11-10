"""a2c_template_llm.py — A2C/G2C template mode through the E2A LLM boundary.

build_template_llm() returns an E2A SimulatedLLMService whose rules answer
every G2C generator prompt and every A2C SDLC agent prompt with a curated,
deterministic artifact:

  G2C  E2A abstract / A2C abstract / inherited class  -> generator_templates
  A2C  RequirementsAgent  -> specification (Markdown)
       IaCAgent           -> templates/terraform/<cloud>.tf
       CICDAgent          -> templates/ci/delivery.yml
       CodeGenAgent       -> templates/code/<language>/{observability,nfr,service}
       CodeCriticAgent    -> JSON score from the deterministic NFR pattern check

Nothing else changes: the generators and agents still call
config['llm_service'], so permits, quotas, DLP, critics and idempotency run
exactly as they would in front of a hosted model. Replacing the service with
a real provider adapter switches A2C to model-generated artifacts.
"""
import ast
import json
import re
from typing import Dict, List, Optional

import generator_templates as T
from a2c_assets import read_template
from a2c_base import MANDATORY_NFRS, nfr_pattern_report
from e2a_simulated_llm import SimulatedLLMService, system_contains

CODE_FILES = {'python': {'observability': 'observability.py', 'nfr': 'nfr.py', 'business': 'service.py'},
              'java': {'observability': 'Observability.java', 'nfr': 'NfrSupport.java',
                       'business': 'Service.java'}}


# ------------------------------------------------------------------ naming
def project_slug(name: str) -> str:
    """'SettlementEngine' -> 'settlement-engine' (cloud resource prefix)."""
    s = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '-', name.strip())
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-') or 'service'


def class_prefix(name: str) -> str:
    """'settlement-engine' / 'SettlementEngine' -> 'SettlementEngine'."""
    parts = re.split(r'[^A-Za-z0-9]+', name.strip())
    return ''.join(p[:1].upper() + p[1:] for p in parts if p) or 'App'


def code_artifact_paths(language: str, project_name: str, package_name: str = None,
                        group_id: str = None) -> Dict[str, str]:
    """Where A2C writes code inside a P0 scaffold, so it is part of the build:
    Python under src/<package>/generated/, Java under <group_id>.generated."""
    if language == 'java' and group_id:
        base = f"src/main/java/{group_id.replace('.', '/')}/generated"
        return {'generated_observability': f'{base}/Observability.java',
                'generated_nfr_module': f'{base}/NfrSupport.java',
                'generated_code': f'{base}/{class_prefix(project_name)}Service.java'}
    if language == 'python' and package_name:
        base = f'src/{package_name}/generated'
        return {'generated_observability': f'{base}/observability.py',
                'generated_nfr_module': f'{base}/nfr.py',
                'generated_code': f'{base}/service.py'}
    return {}


# ----------------------------------------------------------------- helpers
def _system(messages) -> str:
    return '\n'.join(str(m.get('content', '')) for m in messages if m.get('role') == 'system')


def _user(messages) -> str:
    users = [m for m in messages if m.get('role') == 'user']
    return str(users[-1].get('content', '')) if users else ''


def _find(pattern: str, text: str, default: Optional[str] = None) -> Optional[str]:
    m = re.search(pattern, text)
    return m.group(1).strip() if m else default


def _render(template: str, values: Dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace('{{' + key + '}}', value)
    return template


def _values(project: str, cloud: str = 'aws', java_package: str = None) -> Dict[str, str]:
    return {'project': project, 'project_slug': project_slug(project),
            'class_prefix': class_prefix(project), 'cloud': cloud,
            'java_package': java_package or 'com.example.generated'}


def _nfrs_from(text: str) -> List[str]:
    """NFR names listed after 'Mandatory NFRs:' or 'Required NFRs:'."""
    raw = _find(r'(?:Mandatory|Required) NFRs:\s*(.+)', text, '')
    if raw.startswith('['):
        try:
            return [str(n) for n in ast.literal_eval(raw)]
        except (ValueError, SyntaxError):
            pass
    return [n.strip() for n in raw.split(',') if n.strip()]


# ------------------------------------------------------------- G2C rules
def _g2c_e2a_abstract(messages, ctx):
    runtime = _find(r'for runtime (\w+)', _user(messages), 'python')
    return T.e2a_abstract(runtime)


def _g2c_a2c_abstract(messages, ctx):
    runtime = _find(r'for runtime (\w+)', _user(messages), 'python')
    return T.a2c_abstract(runtime)


def _g2c_inherited(kind):
    def respond(messages, ctx):
        user = _user(messages)
        agent = _find(r'Generate class (\w+)', user, 'GeneratedAgent')
        runtime = _find(r'for runtime (\w+)', user, 'python')
        import_line = _find(r'Import line: (.+)', user, '')
        package = _find(r'Java package: (\S+)', user)
        nfrs = _nfrs_from(user) if kind == 'a2c_inherited' else None
        return T.inherited(kind, runtime, agent, import_line, nfrs, package=package)
    return respond


# ------------------------------------------------------------- A2C rules
def _a2c_spec(messages, ctx):
    user = _user(messages)
    project = _find(r'Project: ([^;\n]+)', user, 'the service')
    context = _find(r'Project context: (.+)', user, '')
    nfrs = list(dict.fromkeys(_nfrs_from(user) + MANDATORY_NFRS))
    rows = '\n'.join(f'| {n} | {_MECHANISM.get(n, "Enforced in the NFR module and verified by tests")} |'
                     for n in nfrs)
    return f"""# {project} — specification (A2C RequirementsAgent)

## Context
{context}

## Clean Architecture layer map
| Layer | Responsibility | Location |
|---|---|---|
| Data model | Request/response DTOs and events | models / domain |
| Interface contract | Ports for stores, queues and tools | services (interfaces) |
| Service layer | Domain logic behind one public entry point | services |
| Exposure layer | HTTP routes and queue handlers | routers / controller |

## Mandatory NFRs and their enforcing mechanism
| NFR | Mechanism |
|---|---|
{rows}

## E2A class mapping
| E2A class | Use in this service |
|---|---|
| BaseAgent / BaseWorkflow | Agentic steps, when the service reasons with a model |
| BaseToolService | Every outbound integration (REST or MCP) |
| BaseIdempotencyStore | Claim per request_id before any material effect |
| BaseObservability | Structured logs, traces, metrics, SLO evidence |
"""


_MECHANISM = {
    'Idempotency': 'Atomic claim per (tenant, request_id) before the material effect; replay returns the stored result',
    'Observability': 'JSON logs with correlation id, operation timing, counters, p95 SLO check',
    'CircuitBreaker': 'Breaker per dependency; open circuit fails fast',
    'RetryWithBackoff': 'Bounded retries with jittered exponential backoff and a retry budget',
    'HealthCheck': 'Liveness endpoint used by the container platform',
    'GracefulShutdown': 'SIGTERM stops intake and drains in-flight work',
    'TransactionalOutbox': 'State change and outbound event committed in one transaction; a sweeper publishes',
    'SagaCompensation': 'Each saga step has an idempotent compensating action',
    'Audit': 'Every material decision is recorded with its evidence',
    'DeadLetterQueue': 'Poison messages move to a DLQ after bounded redelivery',
}


def _a2c_iac(messages, ctx):
    system = _system(messages)
    project = _find(r'Generate Terraform for (.+?) on (?:\w+):', system, 'service')
    cloud = _find(r'Generate Terraform for .+? on (\w+):', system, 'aws').lower()
    cloud = cloud if cloud in ('aws', 'gcp', 'azure') else 'aws'
    return _render(read_template(f'terraform/{cloud}.tf'), _values(project, cloud))


def _a2c_cicd(messages, ctx):
    user = _user(messages)
    project = _find(r'Project: ([^;\n]+)', user, 'service')
    cloud = _find(r'Cloud: (\w+)', user, 'aws')
    return _render(read_template('ci/delivery.yml'), _values(project, cloud))


def _a2c_code(messages, ctx):
    system, user = _system(messages), _user(messages)
    language = _find(r'generating production-ready (\w+) code', system, 'python').lower()
    language = language if language in CODE_FILES else 'python'
    project = _find(r'named (.+?) for \w+\.', system, 'Service')
    cloud = _find(r'named .+? for (\w+)\.', system, 'aws')
    if 'ONLY the observability module' in system:
        mode = 'observability'
    elif 'ONLY the NFR module' in system:
        mode = 'nfr'
    else:
        mode = 'business'
    package = _find(r'Java package: (\S+)', user)
    template = read_template(f'code/{language}/{CODE_FILES[language][mode]}')
    return _render(template, _values(project, cloud, package))


def _a2c_critic(messages, ctx):
    user = _user(messages)
    nfrs = _nfrs_from(user) or list(MANDATORY_NFRS)
    code = user.split('Code:', 1)[1] if 'Code:' in user else ''
    report = nfr_pattern_report(code, nfrs)
    return json.dumps({'score': report['score'], 'missing': report['missing'],
                       'passed': report['passed']})


# ------------------------------------------------------------------ factory
def build_template_llm(config: Dict = None) -> SimulatedLLMService:
    """The A2C template-mode LLM: deterministic G2C and A2C artifacts."""
    llm = SimulatedLLMService(config=config)
    (llm
     .add_rule('g2c:e2a_abstract', system_contains('E2A Architecture Framework base abstract'),
               _g2c_e2a_abstract)
     .add_rule('g2c:a2c_abstract', system_contains('Generate the A2C base abstract class'),
               _g2c_a2c_abstract)
     .add_rule('g2c:e2a_inherited', system_contains('Generate an inherited E2A agent'),
               _g2c_inherited('e2a_inherited'))
     .add_rule('g2c:a2c_inherited', system_contains('Generate an inherited A2C agent'),
               _g2c_inherited('a2c_inherited'))
     .add_rule('a2c:requirements', system_contains('requirements architect'), _a2c_spec)
     .add_rule('a2c:iac', system_contains('cloud infrastructure engineer'), _a2c_iac)
     .add_rule('a2c:cicd', system_contains('CI/CD engineer'), _a2c_cicd)
     .add_rule('a2c:critic', system_contains('You are a senior architect'), _a2c_critic)
     .add_rule('a2c:codegen', system_contains('generating production-ready'), _a2c_code))
    return llm