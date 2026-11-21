"""base_generator_agent.py — G2C BaseGeneratorAgent (G2C Framework Reference §4, §17).

One public entry point, generate(request, config) -> GeneratorResult, with a
fixed 12-step sequence. Subclasses override protected hooks only:

  ABSTRACT   _validate_request, _build_user_prompt, _evaluate_output,
             _write_output, _template_output
  PROTECTED  _resolve_config, _build_system_prompt, _apply_policy, _prepare,
             _fallback, _handle_error, _write_file (base-owned helper)
  BASE-OWNED _infer (the only model call, through config['llm_service'])
  PRIVATE    __generate_key, __track_tokens, __load_prompt_file

Concurrency contract (§17):
  * One owner per generator_key. With config['idempotency_store'] the claim is
    atomic and settled on every exit path; without a store the guarantee is
    single-process only.
  * All model calls (generation and critic) go through config['llm_service'];
    a generator holds no semaphore, rate limiter or provider SDK.
  * request['deadline_ms'] (or config['deadline']) caps every wait and is
    checked at each step boundary; a cancelled run settles retryable.
  * Model failures settle retryable (nothing written yet). A failure after
    writing began settles UNKNOWN and is left for reconciliation. A critic
    score below the threshold after two regenerations settles final.

Without config['llm_service'] a generator runs in TEMPLATE mode: it emits a
deterministic skeleton from _template_output() that passes the same critic.
"""
import contextvars
import json
import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from pathlib import Path

from a2c_concurrency import (
    ClaimGuard, DeadlineExceeded, Deadline, InferenceRejected,
    check_deadline, fingerprint_of, run_coro_sync, status_of,
)

RUNTIME_PATTERNS = {
    'python': {'abstract_base': 'from abc import ABC, abstractmethod',
               'abstract_method': '@abstractmethod', 'private_prefix': '__',
               'protected_prefix': '_', 'type_hints': 'from typing import Any, Dict, List, Optional',
               'extension': '.py'},
    'java':   {'abstract_base': 'public abstract class', 'abstract_method': 'protected abstract',
               'private_prefix': 'private', 'protected_prefix': 'protected',
               'type_hints': 'import java.util.*', 'extension': '.java'},
    'node':   {'abstract_base': 'abstract class', 'abstract_method': 'abstract',
               'private_prefix': '#', 'protected_prefix': 'protected',
               'type_hints': 'import type { ... }', 'extension': '.ts'},
    'go':     {'abstract_base': 'type BaseAgent interface', 'abstract_method': '// interface method',
               'private_prefix': 'lowercase', 'protected_prefix': 'lowercase',
               'type_hints': '', 'extension': '.go'},
}

_HERE = Path(__file__).resolve().parent


def _setting(key, config, env, default, cast=float):
    """config dict > environment variable > default (E2A resolution order)."""
    if config and config.get(key) is not None:
        return cast(config[key])
    if os.getenv(env) is not None:
        return cast(os.getenv(env))
    return cast(default)


# v1.6.0 (EV-01, 2.2): the model call the critic is part of (key, tenant, trace, deadline), so the
# optional semantic review runs under the same claim and limits without changing the hook signatures
_CRITIC_CALL = contextvars.ContextVar('a2c_critic_call', default=None)

SEMANTIC_REVIEW_PROMPT = (
    'You review a source file generated for the E2A framework. Score 0.0-1.0: does it do what the '
    'request asks, with correct logic (not only the right structure)? Look for wrong or missing '
    'behaviour, hooks that ignore their inputs, unsafe defaults and contradictions with the request. '
    'Return JSON only: {"score": float, "missing": ["..."]}')


class BaseGeneratorAgent(ABC):
    generator_name = "BaseGeneratorAgent"
    generator_type = ""                 # set by each concrete generator
    critic_type = ""                    # GeneratorCriticAgent rule set
    idempotency = True
    APPROVED_RUNTIMES = ["python", "java", "node", "go"]
    APPROVED_GENERATOR_TYPES = ["e2a_abstract", "a2c_abstract", "e2a_inherited", "a2c_inherited"]
    PROMPT_DIR = "prompts/"
    MIN_CRITIC_SCORE = 0.75
    MAX_REGENERATIONS = 2
    MAX_TOKENS = 32000
    MAX_LATENCY_MS = 60000

    def __init__(self, config=None, **kwargs):
        self.config = config or {}

    # ------------------------------------------------------------------ public
    def generate(self, request, config=None, **kwargs):
        """Single public entry point. Never override.

        Steps: 1 resolve · 2 validate · 3 policy · 4 claim · 5 system prompt ·
        6 user prompt · 7 token budget · 8 model call · 9 critic ·
        10 regeneration (≤ 2) · 11 write · 12 latency SLO + log.
        Typed outcomes are returned; a validation/policy failure raises
        ValueError; an unexpected exception propagates after the claim is settled.
        """
        config = config or getattr(self, 'config', None) or {}
        request = dict(request or {})
        trace_id = str(uuid.uuid4())
        start = time.time()

        # Step 1 — resolve
        if request.get('source', 'inline') in ('json', 'prompt'):
            request = self._resolve_config(request, config, **kwargs)
        # Step 2 — validate
        if not self._validate_request(request, config, **kwargs):
            raise ValueError(f"[{self.generator_name}] invalid GeneratorRequest")
        # Step 3 — governance
        self._apply_policy(request, config, **kwargs)
        tenant_id = request.get("tenant_id") or config.get("tenant_id")

        key = self.__generate_key(request)
        deadline = Deadline.from_request(request, config)
        guard = ClaimGuard(
            config.get("idempotency_store") if self.idempotency else None,
            f"g2c:{key}", tenant_id,      # claim namespace: never collides with P0/A2C/AI-DLC keys
            fingerprint_of(request, exclude=request.get('fingerprint_exclude') or ()),
            config, lease_seconds=float(config.get("claim_lease_seconds", 300)))
        writing_started = False
        result = {"success": False, "generator_key": key, "trace_id": trace_id, "errors": []}
        try:
            # Step 4 — idempotency claim
            claim = guard.acquire()
            if not guard.owned:
                return self._not_owner(claim, key, trace_id)
            if guard.store is None and self.idempotency:
                # GENERATOR_IDEMPOTENCY_STORE='local': without a claim store the
                # output location is the (single-process) idempotency check.
                existing = self._existing_output(request, config)
                if existing:
                    result.update(success=True, status="replay", replayed=True,
                                  generated_files=existing)
                    return result

            # Inherited generators resolve the abstract class and run P0 here
            # (their phases 5–8). Both are idempotent, so this is not a write
            # that would make a later failure UNKNOWN.
            check_deadline(deadline, "preparation")
            prepared = self._prepare(request, config, deadline=deadline, **kwargs) or {}
            result.update(prepared.get('result', {}))
            if prepared.get('abort'):
                outcome = prepared['abort']
                result.update(status=outcome['status'], errors=outcome.get('errors', []))
                guard.fail(retryable=outcome.get('retryable', True))
                return result

            # Steps 5–7 — prompts and token budget
            check_deadline(deadline, "prompt build")
            system_prompt = self._build_system_prompt(request, config, **kwargs)
            user_prompt = self._build_user_prompt(request, config, **kwargs)
            tokens = self.__track_tokens([system_prompt, user_prompt])
            max_tokens = _setting('max_tokens', config, 'GENERATOR_MAX_TOKENS', self.MAX_TOKENS, int)
            if tokens > max_tokens:
                raise ValueError(f"token budget exceeded: ~{tokens} > {max_tokens}")

            # Steps 8–10 — model call, critic, regeneration
            response, score, attempts, mode = self._generate_with_critic(
                system_prompt, user_prompt, request, config, deadline, key, tenant_id,
                trace_id, **kwargs)
            report = dict(request.get('critic_report') or {})
            report.update(score=score, attempts=attempts, mode=mode)
            result['critic_report'] = report
            threshold = _setting('min_critic_score', config, 'GENERATOR_MIN_CRITIC_SCORE',
                                 self.MIN_CRITIC_SCORE)
            if score < threshold:
                guard.fail(retryable=False)
                return self._handle_error(
                    RuntimeError(f"critic score {score:.2f} below {threshold} after "
                                 f"{self.MAX_REGENERATIONS} regenerations; missing: "
                                 f"{report.get('missing', [])}"),
                    request, result, config, status="critic_threshold_not_met")

            # Step 11 — write
            check_deadline(deadline, "writing output")
            writing_started = True
            files = self._write_output(response, request, config, **kwargs)
            result.update(success=True, status="generated",
                          generated_files=list(prepared.get('files_before', [])) + list(files))
            for k in ('abstract_class_path', 'abstract_class_generated_fresh',
                      'e2a_abstract_class_path', 'project_root'):
                if request.get(k) is not None and k not in result:
                    result[k] = request[k]

            # Step 12 — latency SLO + observability
            latency = (time.time() - start) * 1000
            result["latency_ms"] = round(latency, 2)
            max_ms = _setting('max_latency_ms', config, 'GENERATOR_MAX_LATENCY_MS', self.MAX_LATENCY_MS)
            if latency > max_ms:
                logging.warning(f"[{self.generator_name}] latency SLO breach: "
                                f"{latency:.0f}ms > {max_ms:.0f}ms")
            guard.succeed(result)
            logging.info({"generator": self.generator_name, "generator_key": key,
                          "trace_id": trace_id, "latency_ms": result["latency_ms"],
                          "tokens": tokens, "score": score, "attempts": attempts, "mode": mode})
            return result

        except DeadlineExceeded as e:
            guard.settle_exception(e, side_effects_possible=writing_started)
            return self._handle_error(e, request, result, config, status="deadline_exceeded")
        except InferenceRejected as e:
            guard.settle_exception(e, side_effects_possible=False)
            result["retryable"] = True
            return self._handle_error(e, request, result, config, status="inference_rejected",
                                      error_text=f"{e.error_type}: {e}")
        except BaseException as e:      # incl. cancellation: never leave a claim IN_PROGRESS
            guard.settle_exception(e, side_effects_possible=writing_started)
            raise

    # ------------------------------------------------------------- abstract hooks
    @abstractmethod
    def _validate_request(self, request, config=None, **kwargs) -> bool:
        """Required GeneratorRequest fields for this generator."""

    @abstractmethod
    def _build_user_prompt(self, request, config=None, **kwargs) -> str:
        """Developer-facing prompt from request fields."""

    @abstractmethod
    def _evaluate_output(self, response, request, config=None, **kwargs) -> float:
        """Score 0.0–1.0 via GeneratorCriticAgent; set request['critic_report']."""

    @abstractmethod
    def _write_output(self, response, request, config=None, **kwargs):
        """Write the generated file(s) with runtime-correct names; return paths."""

    @abstractmethod
    def _template_output(self, request, config=None, **kwargs) -> str:
        """Deterministic skeleton used when no llm_service is bound."""

    # ---------------------------------------------------------- protected hooks
    def _resolve_config(self, request, config=None, **kwargs):
        """source='json': merge the 'generator' section of config_path (inline
        fields win; a top-level 'scaffold' section becomes request['scaffold']).
        source='prompt': not supported by the generators — the user prompt is
        already free text (request['user_prompt'])."""
        if request.get('source') == 'json':
            with open(request['config_path'], encoding='utf-8') as f:
                data = json.load(f)
            loaded = dict(data.get('generator', data))
            if 'scaffold' in data and 'scaffold' not in loaded:
                loaded['scaffold'] = data['scaffold']
            inline = {k: v for k, v in request.items() if k not in ('source', 'config_path')}
            merged = {**loaded, **inline}
            merged.update(source='inline', resolved_from='json')
            return merged
        if request.get('source') == 'prompt':
            raise ValueError("generators take free text in user_prompt; use source='inline' or 'json'")
        return request

    def _apply_policy(self, request, config=None, **kwargs) -> None:
        """Governance: approved runtime and generator type, optional NFR
        allow-list, tenant required when a gateway is used."""
        config = config or {}
        if request.get("runtime") not in self.APPROVED_RUNTIMES:
            raise ValueError(f"Unsupported runtime: {request.get('runtime')}")
        gtype = request.get("generator_type") or self.generator_type
        if gtype and gtype not in self.APPROVED_GENERATOR_TYPES:
            raise ValueError(f"Unsupported generator_type: {gtype}")
        allowed = config.get("approved_nfrs")
        if allowed is not None:
            bad = [n for n in request.get("mandatory_nfrs", []) if n not in allowed]
            if bad:
                raise PermissionError(f"NFRs not in approved list: {bad}")
        if config.get("llm_service") is not None and not (
                request.get("tenant_id") or config.get("tenant_id")):
            raise ValueError("tenant_id is required when generating through llm_service")

    def _existing_output(self, request, config=None):
        """Paths of an earlier run's output, or None. Consulted only when no
        idempotency store is configured. Default: None (always generate)."""
        return None

    def _prepare(self, request, config=None, **kwargs) -> dict:
        """Hook between the claim and the prompts. Default: nothing.
        Return {'result': {...}} to merge fields into the result,
        {'files_before': [...]} for files already produced, or
        {'abort': {'status', 'errors', 'retryable'}} to stop."""
        return {}

    def _build_system_prompt(self, request, config=None, **kwargs) -> str:
        """Versioned base prompt + runtime patterns + system_prompt_additions.
        Unknown placeholders render empty, so prompt files can evolve."""
        base = self.__load_prompt_file(f"{self.generator_name.lower()}_system_v1.txt", config)
        runtime = request.get("runtime", "python")
        values = defaultdict(str, {
            'runtime': runtime,
            'runtime_version': request.get('runtime_version', ''),
            'runtime_patterns': json.dumps(RUNTIME_PATTERNS.get(runtime, RUNTIME_PATTERNS['python'])),
            'idempotency': request.get('idempotency', True),
            'async_mode': request.get('async_mode', True),
            'domain': request.get('domain', 'general'),
            'agent_name': request.get('agent_name', ''),
            'base_class_name': request.get('base_class_name', ''),
            'system_prompt_additions': request.get('system_prompt_additions', ''),
            'abstract_class_content': self._abstract_context(request),
        })
        return base.format_map(values)

    def _abstract_context(self, request) -> str:
        """Abstract-class content given to the model as context (inherited
        generators override; abstract generators have none by default)."""
        return ''

    def _fallback(self, request, config=None, **kwargs) -> str:
        """Stricter-prompt addendum for a regeneration."""
        missing = (request.get('critic_report') or {}).get('missing') or []
        return ("The previous output failed the structural quality gate. "
                f"Fix these issues and return only the source file: {missing}")

    def _handle_error(self, error, request, result, config=None, status="failed",
                      error_text=None, **kwargs):
        """Log, append to errors, set a typed status, return a safe result."""
        logging.error(f"[{self.generator_name}][{result.get('generator_key')}] {error}")
        result.setdefault("errors", []).append(error_text or str(error))
        result.update(success=False, status=status)
        return result

    def _critic_review(self, response, request, config=None) -> float:
        """Run GeneratorCriticAgent with this generator's critic_type; store
        the report in request['critic_report'] and return the score."""
        from generator_critic_agent import GeneratorCriticAgent
        critic_cfg = dict((config or {}).get('critic_config') or {})
        critic_cfg.setdefault('critic_type', self.critic_type or request.get('generator_type'))
        report = GeneratorCriticAgent(critic_cfg).review(response, request)
        semantic = self._semantic_review(response, request, config or {}, report)
        if semantic is not None:            # v1.6.0: the lower score wins, as in A2C's CodeCriticAgent
            report['structural_score'] = report['score']
            report['semantic'] = semantic
            report['score'] = round(min(report['score'], semantic['score']), 4)
            report['missing'] = list(report['missing']) + [f'semantic: {m}' for m in semantic['missing']]
        request['critic_report'] = report
        return report['score']

    def _semantic_review(self, response, request, config, structural):
        """Optional model review (v1.6.0, EV-01 2.2; G2C O-1). Runs only when a critic model is
        named (request['critic_model_id'], config['critic_model_id'] or GENERATOR_CRITIC_MODEL_ID)
        and a model is bound; never on output the structural check already scored 0.0. Goes
        through config['llm_service'] like every model call; a rejected call raises
        InferenceRejected (retryable). An unreadable review scores 0.0. Returns None when skipped."""
        model_id = (request.get('critic_model_id') or (config or {}).get('critic_model_id')
                    or os.getenv('GENERATOR_CRITIC_MODEL_ID'))
        service = (config or {}).get('llm_service')
        if not model_id or service is None or structural.get('score', 0.0) <= 0.0:
            return None
        call = _CRITIC_CALL.get() or {}
        source = response if isinstance(response, str) else str(response or '')
        messages = [{'role': 'system', 'content': SEMANTIC_REVIEW_PROMPT},
                    {'role': 'user', 'content': (
                        f"Generator: {self.generator_type or request.get('generator_type', '')}; runtime: "
                        f"{request.get('runtime', 'python')}; class: "
                        f"{request.get('agent_name') or request.get('base_class_name') or ''}\n"
                        f"Request: {request.get('description') or request.get('user_prompt') or ''}\n\n"
                        f"Source:\n{source}")}]
        out = run_coro_sync(service.process_inference(
            messages, tenant_id=call.get('tenant_id') or request.get('tenant_id'), deadline=call.get('deadline'),
            correlation_id=call.get('trace_id'), idempotency_key=call.get('key'), model_id=model_id))
        if out.get('status') != 'SUCCESS':
            raise InferenceRejected(out.get('error', 'critic model call failed'),
                                    out.get('error_type', 'InferenceRejected'))
        try:
            review = json.loads(_strip_fences(out.get('text', '')) or '{}')
            score = max(0.0, min(1.0, float(review.get('score', 0.0))))
            missing = [str(m) for m in (review.get('missing') or [])]
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            score, missing = 0.0, ['the semantic review was not readable JSON']
        return {'score': round(score, 4), 'missing': missing, 'model_id': model_id}

    def _write_file(self, root, relative_path, content) -> str:
        """Base-owned writer for subclasses: mkdir -p, write UTF-8, absolute path."""
        return self.__write_file(root, relative_path, content)

    def _infer(self, system_prompt, user_prompt, request, config, deadline,
               idempotency_key, tenant_id, trace_id, **kwargs) -> str:
        """The only model call. Goes through config['llm_service'] (E2A's
        BaseLLMAgentService): tenant-and-pod permit, RPM/TPM quota, per-call
        timeout. A rejected or failed call raises InferenceRejected."""
        service = config.get("llm_service")
        if service is None:
            return self._template_output(request, config, **kwargs)
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}]
        extra = {}
        if request.get("model_id"):
            extra["model_id"] = request["model_id"]
        out = run_coro_sync(service.process_inference(
            messages, tenant_id=tenant_id, deadline=deadline, correlation_id=trace_id,
            idempotency_key=idempotency_key, **extra))
        if out.get("status") != "SUCCESS":
            raise InferenceRejected(out.get("error", "model call failed"),
                                    out.get("error_type", "InferenceRejected"))
        return _strip_fences(out.get("text", ""))

    # ------------------------------------------------------------------ private
    def __generate_key(self, request) -> str:
        """name:type:runtime:platform (tenant scoping is applied by the claim)."""
        return ":".join([str(request.get("agent_name") or request.get("base_class_name")
                             or self.generator_name),
                         str(request.get("generator_type") or self.generator_type),
                         str(request.get("runtime", "")),
                         str(request.get("platform", "standalone"))])

    # kept for callers of the previous name
    def _generator_key(self, request) -> str:
        return self.__generate_key(request)

    @staticmethod
    def __track_tokens(texts) -> int:
        """FinOps estimate (~4 characters per token)."""
        return max(1, sum(len(t or '') for t in texts) // 4)

    def __load_prompt_file(self, filename, config=None) -> str:
        base = (config or {}).get('prompt_dir') or os.getenv('GENERATOR_PROMPT_DIR') or self.PROMPT_DIR
        path = Path(base) / filename
        if not path.is_absolute() and not path.exists():
            path = _HERE / base / filename
        if not path.exists() and base == self.PROMPT_DIR:
            from a2c_assets import PROMPTS_DIR      # installed package layout
            path = PROMPTS_DIR / filename
        return path.read_text(encoding='utf-8') if path.exists() else ''

    @staticmethod
    def __write_file(root, relative_path, content) -> str:
        full = Path(root) / relative_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content if content.endswith('\n') else content + '\n', encoding='utf-8')
        return str(full.resolve())

    def _generate_with_critic(self, system_prompt, user_prompt, request, config, deadline,
                              key, tenant_id, trace_id, **kwargs):
        """Generate, score, and regenerate with a stricter prompt up to
        MAX_REGENERATIONS times. The critic adds no model call of its own."""
        attempts, score, response = 0, 0.0, ""
        threshold = _setting('min_critic_score', config, 'GENERATOR_MIN_CRITIC_SCORE',
                             self.MIN_CRITIC_SCORE)
        mode = 'model' if config.get('llm_service') is not None else 'template'
        prompt = user_prompt
        for attempt in range(self.MAX_REGENERATIONS + 1):
            check_deadline(deadline, f"model call {attempt + 1}")
            attempts += 1
            response = self._infer(system_prompt, prompt, request, config, deadline,
                                   f"{key}:attempt{attempt}", tenant_id, trace_id, **kwargs)
            check_deadline(deadline, "critic")
            token = _CRITIC_CALL.set({'key': f"{key}:critic{attempt}", 'tenant_id': tenant_id,
                                      'trace_id': trace_id, 'deadline': deadline})
            try:
                score = self._evaluate_output(response, request, config, **kwargs)
            finally:
                _CRITIC_CALL.reset(token)
            if score >= threshold:
                break
            prompt = user_prompt + "\n\n" + str(self._fallback(request, config, **kwargs))
        return response, score, attempts, mode

    @staticmethod
    def _not_owner(claim, key, trace_id):
        """Typed outcome for a caller that does not own the key."""
        st = status_of(claim)
        if st == "REPLAY":
            stored = dict(claim.result or {})
            missing = [f for f in stored.get("generated_files", []) if not Path(f).exists()]
            if missing:
                # Settled output was removed (e.g. by a saga): never replay
                # paths that no longer exist.
                return {"success": False, "status": "recovery_required", "generator_key": key,
                        "trace_id": trace_id,
                        "errors": [f"replayed output is missing: {missing}; reconcile the claim "
                                   "before regenerating"]}
            stored.update(status="replay", replayed=True)
            return stored          # idempotent no-op: nothing is written
        messages = {
            "IN_PROGRESS": "another run holds this generator_key",
            "CONFLICT": "same generator_key presented with a different request",
            "RECOVERY_REQUIRED": "a previous owner's claim expired without settling; "
                                 "reconcile before re-running",
            "FAILED_FINAL": "this generator_key failed finally and is not re-executed",
        }
        return {"success": False, "status": st.lower(), "generator_key": key,
                "trace_id": trace_id, "errors": [messages.get(st, st)]}


def _strip_fences(text: str) -> str:
    """Remove a single surrounding ``` fence a model may add."""
    t = (text or '').strip()
    if t.startswith('```'):
        t = t.split('\n', 1)[1] if '\n' in t else ''
        if t.rstrip().endswith('```'):
            t = t.rstrip()[:-3]
    return t
