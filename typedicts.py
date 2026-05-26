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
