import logging
import time
import uuid
from abc import ABC, abstractmethod

from a2c_concurrency import (
    ClaimGuard, DeadlineExceeded, Deadline, InferenceRejected,
    check_deadline, fingerprint_of, run_coro_sync, status_of,
)


class BaseGeneratorAgent(ABC):
    """Single public entry point: generate(request, config) -> GeneratorResult.

    Concurrency contract (G2C Framework Reference, Section 17):
      * One owner per generator_key. When config['idempotency_store'] is set,
        generate() takes an atomic claim before the first model call and
        settles it on every exit path. Without a store the guarantee is
        single-process only.
      * All model calls (generation and critic) go through
        config['llm_service']; the generator holds no semaphore, rate limiter
        or provider SDK of its own. Without config['llm_service'] the
        simplified stub response below is used (test double).
      * request['deadline_ms'] (or config['deadline']) caps every wait and is
        checked at each step boundary; a cancelled run settles its claim as
        retryable.
      * Model failures settle retryable (no file has been written yet). A
        failure after writing began settles UNKNOWN and is left for
        reconciliation, never re-run blindly. A critic score below
        GENERATOR_MIN_CRITIC_SCORE after two regenerations settles final.
    """
    generator_name = "BaseGeneratorAgent"
    idempotency = True
    APPROVED_RUNTIMES = ["python", "java", "node", "go"]
    APPROVED_GENERATOR_TYPES = ["e2a_abstract", "a2c_abstract", "e2a_inherited", "a2c_inherited"]
    PROMPT_DIR = "prompts/"
    MIN_CRITIC_SCORE = 0.75
    MAX_REGENERATIONS = 2

    # ------------------------------------------------------------------ public
    def generate(self, request, config=None, **kwargs):
        config = config or {}
        trace_id = str(uuid.uuid4())
        start = time.time()
        key = self._generator_key(request)

        if not self.validate_request(request, config, **kwargs):
            raise ValueError("Invalid request")
        if request.get("runtime") not in self.APPROVED_RUNTIMES:
            raise ValueError("Unsupported runtime")
        gtype = request.get("generator_type")
        if gtype is not None and gtype not in self.APPROVED_GENERATOR_TYPES:
            raise ValueError("Unsupported generator_type")
        tenant_id = request.get("tenant_id") or config.get("tenant_id")
        if config.get("llm_service") is not None and not tenant_id:
            raise ValueError("tenant_id is required when generating through llm_service")

        deadline = Deadline.from_request(request, config)
        guard = ClaimGuard(
            config.get("idempotency_store") if self.idempotency else None,
            key, tenant_id, fingerprint_of(request), config,
            lease_seconds=float(config.get("claim_lease_seconds", 300)))
        writing_started = False
        try:
            claim = guard.acquire()
            if not guard.owned:
                return self._not_owner(claim, key, trace_id)

            check_deadline(deadline, "prompt build")
            system_prompt = self.build_system_prompt(request, config, **kwargs)
            user_prompt = self.build_user_prompt(request, config, **kwargs)

            response, score, attempts = self._generate_with_critic(
                system_prompt, user_prompt, request, config, deadline, key, tenant_id,
                trace_id, **kwargs)
            if score < self.MIN_CRITIC_SCORE:
                result = {"success": False, "status": "critic_threshold_not_met",
                          "generator_key": key, "trace_id": trace_id,
                          "critic_report": {"score": score, "attempts": attempts},
                          "errors": [f"critic score {score:.2f} below {self.MIN_CRITIC_SCORE} "
                                     f"after {self.MAX_REGENERATIONS} regenerations"]}
                guard.fail(retryable=False)
                return result

            check_deadline(deadline, "writing output")
            writing_started = True
            files = self.write_output(response, request, config, **kwargs)
            result = {"success": True, "status": "generated", "generator_key": key,
                      "generated_files": files, "trace_id": trace_id,
                      "critic_report": {"score": score, "attempts": attempts},
                      "latency_ms": round((time.time() - start) * 1000, 2)}
            guard.succeed(result)
            logging.info({"generator": self.generator_name, "generator_key": key,
                          "trace_id": trace_id, "score": score, "attempts": attempts})
            return result

        except DeadlineExceeded as e:
            guard.settle_exception(e, side_effects_possible=writing_started)
            return {"success": False, "status": "deadline_exceeded", "generator_key": key,
                    "trace_id": trace_id, "errors": [str(e)]}
        except InferenceRejected as e:
            guard.settle_exception(e, side_effects_possible=False)
            return {"success": False, "status": "inference_rejected", "retryable": True,
                    "generator_key": key, "trace_id": trace_id,
                    "errors": [f"{e.error_type}: {e}"]}
        except BaseException as e:      # incl. cancellation: never leave a claim IN_PROGRESS
            guard.settle_exception(e, side_effects_possible=writing_started)
            raise

    # ------------------------------------------------------------- protected
    @abstractmethod
    def validate_request(self, request, config=None, **kwargs): ...
    @abstractmethod
    def resolve_config(self, request, config=None, **kwargs): ...
    @abstractmethod
    def build_system_prompt(self, request, config=None, **kwargs): ...
    @abstractmethod
    def build_user_prompt(self, request, config=None, **kwargs): ...
    @abstractmethod
    def evaluate_output(self, response, request, config=None, **kwargs): ...
    @abstractmethod
    def write_output(self, response, request, config=None, **kwargs): ...

    def fallback(self, request, config=None, **kwargs):
        """Stricter-prompt addendum used for a regeneration."""
        return f"Fallback regeneration for {self.generator_name}"

    def _infer(self, system_prompt, user_prompt, request, config, deadline,
               idempotency_key, tenant_id, trace_id, **kwargs):
        """The only model call. Goes through config['llm_service'] (E2A's
        BaseLLMAgentService), which applies the tenant-and-pod permit, the
        RPM/TPM quota and the per-call timeout. A rejected or failed call
        raises InferenceRejected (retryable)."""
        service = config.get("llm_service")
        if service is None:
            return f"Generated {self.generator_name} output for {request.get('runtime')}"
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
        return out.get("text", "")

    # --------------------------------------------------------------- private-ish
    def _generator_key(self, request):
        """name:type:runtime:platform (tenant scoping is applied by the claim)."""
        return ":".join([str(request.get("agent_name") or self.generator_name),
                         str(request.get("generator_type", "")),
                         str(request.get("runtime", "")),
                         str(request.get("platform", "standalone"))])

    def _generate_with_critic(self, system_prompt, user_prompt, request, config, deadline,
                              key, tenant_id, trace_id, **kwargs):
        """Generate, score, and regenerate with a stricter prompt up to
        MAX_REGENERATIONS times. The critic's own model call also goes
        through config['llm_service'] (inside evaluate_output)."""
        attempts, score, response = 0, 0.0, ""
        prompt = user_prompt
        for attempt in range(self.MAX_REGENERATIONS + 1):
            check_deadline(deadline, f"model call {attempt + 1}")
            attempts += 1
            response = self._infer(system_prompt, prompt, request, config, deadline,
                                   f"{key}:attempt{attempt}", tenant_id, trace_id, **kwargs)
            check_deadline(deadline, "critic")
            score = self.evaluate_output(response, request, config, **kwargs)
            if score >= self.MIN_CRITIC_SCORE:
                break
            prompt = user_prompt + "\n\n" + str(self.fallback(request, config, **kwargs))
        return response, score, attempts

    @staticmethod
    def _not_owner(claim, key, trace_id):
        """Typed outcome for a caller that does not own the key."""
        st = status_of(claim)
        if st == "REPLAY":
            stored = dict(claim.result or {})
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
