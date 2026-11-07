from typing import TypedDict, List, Dict

class GeneratorRequest(TypedDict, total=False):
    generator_type: str
    runtime: str
    output_path: str
    agent_name: str
    abstract_class_source: str
    abstract_class_path: str
    package_name: str
    scaffold: dict
    model_id: str
    critic_model_id: str
    tenant_id: str            # scopes the idempotency claim
    platform: str             # part of generator_key; default 'standalone'
    deadline_ms: int          # remaining budget; caps every wait

class GeneratorResult(TypedDict, total=False):
    success: bool
    generator_key: str
    generated_files: List[str]
    abstract_class_path: str
    scaffold_result: dict
    critic_report: dict
    trace_id: str
    latency_ms: float
    errors: List[str]
    status: str               # generated | replay | in_progress | conflict | recovery_required
                              # | failed_final | inference_rejected | deadline_exceeded
                              # | critic_threshold_not_met
    replayed: bool            # True when the stored result of an earlier run was returned
    retryable: bool
