"""developer_platform_workflow.py — G2C top-level orchestrator (G2C Framework
Reference §10.2, §17).

DeveloperPlatformWorkflow(config).generate(request, config) -> GeneratorResult

  * One entry point for all four generator types. For inherited types the
    chain (abstract class first when abstract_class_source='generate', then
    P0 when request['scaffold'] is set, then the inherited class) runs inside
    the inherited generator after its claim, so a replay of a settled
    generator_key is the idempotent no-op: the stored result, no model call,
    no scaffold.
  * The result is a flat GeneratorResult (success, status, generator_key,
    generated_files, abstract_class_path, abstract_class_generated_fresh,
    scaffold_result incl. dev_request, critic_report, ...).
  * Shared abstract classes carry a compare-and-set ownership record.
    compensate() removes an abstract class only if this request generated it
    fresh and no other generator_key references it; one loaded from 'path'
    or 'package' is never removed.
"""
import os

from generator_factory import GeneratorFactory
from a2c_concurrency import InMemoryArtifactRegistry, register_artifact, release_artifact

INHERITED = ("e2a_inherited", "a2c_inherited")


class DeveloperPlatformWorkflow:

    def __init__(self, config: dict = None, artifact_registry=None):
        self.config = config or {}
        self.artifact_registry = (artifact_registry or self.config.get('artifact_registry')
                                  or InMemoryArtifactRegistry())

    def generate(self, request: dict, config: dict = None) -> dict:
        config = config if config is not None else self.config
        request = dict(request or {})
        if request.get("generator_type") in INHERITED:
            request.setdefault("abstract_class_source", "generate")
        result = GeneratorFactory.create(request, config).generate(request, config)
        if result.get("success") and request.get("generator_type") in INHERITED:
            fresh = bool(result.get("abstract_class_generated_fresh"))
            for key in ("e2a_abstract_class_path", "abstract_class_path"):
                path = result.get(key)
                if path:
                    register_artifact(self.artifact_registry, path, result["generator_key"],
                                      created_fresh=fresh)
        return result

    def compensate(self, request: dict, result: dict) -> dict:
        """Saga compensation for one request: release this request's
        references and delete an abstract class only where the registry says
        this caller may (creator, last reference, not already deleted)."""
        output = result.get("output", result)       # accepts the older wrapped shape
        key = output.get("generator_key")
        paths = [p for p in (output.get("abstract_class_path") or request.get("abstract_class_path"),
                             output.get("e2a_abstract_class_path")) if p]
        if not key or not paths:
            return {"released": False, "removed": False, "path": paths[0] if paths else None}
        removed, may = [], []
        for path in paths:
            ok = release_artifact(self.artifact_registry, path, key)
            may.append(ok)
            if ok and os.path.isfile(path):
                os.remove(path)
                removed.append(path)
        return {"released": True, "removed": bool(removed), "removed_paths": removed,
                "may_delete": any(may), "path": paths[0]}
