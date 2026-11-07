import re


class GeneratorCriticAgent:
    """Scores generated output 0.0-1.0.

    score() is still a simplified scorer (full structural checks are specified
    in the G2C Framework Reference, Section 8). It now applies the static
    concurrency rules below, which every generated E2A/A2C agent must satisfy:
    model capacity belongs to the shared gateway, so generated code must not
    carry its own semaphore, rate limiter or provider SDK call. The check is a
    text heuristic over the generated source, not a proof.
    """

    CONCURRENCY_RULES = [
        (re.compile(r'\bdef\s+_validate_state\b'),
         'agent-level _validate_state: validation belongs to BaseValidationService'),
        (re.compile(r'\b(?:asyncio|threading)\.(?:Bounded)?Semaphore\b|\bBoundedSemaphore\('),
         'own semaphore: model concurrency is enforced by config["llm_service"]'),
        (re.compile(r'\b(?:RateLimiter|TokenBucket|token_bucket|ratelimit)\b'),
         'own rate limiter: RPM/TPM quota is enforced by config["llm_service"]'),
        (re.compile(r'^\s*(?:import|from)\s+(?:openai|anthropic|google\.generativeai|vertexai)\b',
                    re.M),
         'direct provider SDK import: the model is called only through _infer()'),
        (re.compile(r'invoke_model\(|bedrock-runtime|\.chat\.completions\.create\('),
         'direct provider call: the model is called only through _infer()'),
    ]
    PENALTY = 0.25

    def __init__(self, config=None):
        self.config = config or {}

    def concurrency_findings(self, source):
        """Violations of the shared-gateway rule found in generated source."""
        return [msg for pattern, msg in self.CONCURRENCY_RULES if pattern.search(source or '')]

    def score(self, response, request):
        findings = self.concurrency_findings(response if isinstance(response, str) else '')
        return max(0.0, 1.0 - self.PENALTY * len(findings))
