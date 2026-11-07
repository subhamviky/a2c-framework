"""typedicts.py — G2C input/output contracts (G2C Framework Reference §3)."""
from typing import TypedDict, List, Dict, Any


class GeneratorRequest(TypedDict, total=False):
    # ── Universal ──────────────────────────────────────────────────────────
    generator_type: str        # 'e2a_abstract' | 'a2c_abstract' | 'e2a_inherited' | 'a2c_inherited'
    source: str                # 'inline' (default) | 'json'
    config_path: str           # generator-config.json when source='json'
    runtime: str               # 'python' | 'java' | 'node' | 'go'
    runtime_version: str
    idempotency: bool          # include the idempotency pattern (default True)
    async_mode: bool           # default True
    platform: str              # 'aws' | 'gcp' | 'azure' | 'standalone' (part of generator_key)
    domain: str
    team: str
    company: str
    output_path: str
    tenant_id: str             # scopes the idempotency claim; required with llm_service
    deadline_ms: int           # remaining budget; caps every wait
    # ── Prompt customisation ───────────────────────────────────────────────
    system_prompt_additions: str
    user_prompt: str
    mandatory_nfrs: List[str]
    optional_nfrs: List[str]
    # ── Abstract generators ────────────────────────────────────────────────
    base_class_name: str
    abstract_methods: List[str]
    class_description: str
    # ── Inherited generators ───────────────────────────────────────────────
    agent_name: str
    abstract_class_source: str # 'generate' (default) | 'path' | 'package'
    abstract_class_path: str   # required for 'path'
    abstract_class_config: Dict[str, Any]   # for 'generate'
    package_name: str          # required for 'package'
    scaffold: Dict[str, Any]   # P0 ScaffoldRequest; runs P0 inline
    # ── Model ──────────────────────────────────────────────────────────────
    model_id: str
    critic_model_id: str
    # ── Advanced ───────────────────────────────────────────────────────────
    fingerprint_exclude: List[str]   # fields left out of the claim fingerprint
    # ── Written by generate() ──────────────────────────────────────────────
    generator_key: str
    generated_files: List[str]
    critic_report: Dict[str, Any]
    errors: List[str]


class GeneratorResult(TypedDict, total=False):
    success: bool
    status: str               # generated | replay | in_progress | conflict | recovery_required
                              # | failed_final | inference_rejected | deadline_exceeded
                              # | critic_threshold_not_met | scaffold_failed
    generator_key: str
    generated_files: List[str]
    abstract_class_path: str
    e2a_abstract_class_path: str          # a2c_inherited chain only
    abstract_class_generated_fresh: bool  # this request created the abstract class
    project_root: str
    scaffold_result: Dict[str, Any]       # P0 ScaffoldResult (incl. dev_request)
    critic_report: Dict[str, Any]         # {score, missing, passed, attempts, mode}
    trace_id: str
    latency_ms: float
    errors: List[str]
    replayed: bool
    retryable: bool
