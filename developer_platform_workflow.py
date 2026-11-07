# developer_platform_workflow.py

import os

from generator_factory import GeneratorFactory
from a2c_concurrency import (
    InMemoryArtifactRegistry, register_artifact, release_artifact,
)


class DeveloperPlatformWorkflow:
    """
    Orchestrates generator execution for developer platform use cases.
    Wraps GeneratorFactory and exposes a unified generate() entrypoint.

    Contracts preserved under concurrency (G2C Framework Reference Section 17):
      * generate() stays the single entry point and keeps the embedded
        `scaffold` field (P0 runs inline after an inherited class).
      * A replayed generation (same generator_key already succeeded) is the
        idempotent no-op: the stored result comes back and no abstract class
        is regenerated.
      * Shared abstract classes carry a compare-and-set ownership record.
        compensate() removes an abstract class only if this request generated
        it fresh and no other generator_key references it. An abstract class
        loaded from abstract_class_source='path' or 'package' is never
        removed.
    """

    def __init__(self, config: dict = None, artifact_registry=None):
        self.config = config or {}
        self.artifact_registry = artifact_registry or InMemoryArtifactRegistry()

    def generate(self, generator_request: dict, scaffold_config: dict = None):
        config = scaffold_config if scaffold_config is not None else self.config
        generator_type = generator_request.get("generator_type")
        inherited = generator_type in ("e2a_inherited", "a2c_inherited")

        abstract_fresh = False
        # Chain: generate the abstract class first when it is not supplied.
        if inherited:
            generator_request.setdefault("abstract_class_source", "generate")
            if generator_request["abstract_class_source"] == "generate":
                abstract_type = "e2a_abstract" if generator_type == "e2a_inherited" else "a2c_abstract"
                abstract_request = {
                    **generator_request.get("abstract_class_config", {}),
                    "generator_type": abstract_type,
                    "runtime": generator_request.get("runtime", "python"),
                    "output_path": generator_request.get("output_path", "./") + "common/",
                    "tenant_id": generator_request.get("tenant_id"),
                }
                if generator_request.get("deadline_ms") is not None:
                    abstract_request["deadline_ms"] = generator_request["deadline_ms"]
                abstract_result = GeneratorFactory.create(abstract_type).generate(
                    abstract_request, config=config)
                if not abstract_result.get("success"):
                    return self._wrap(generator_type, abstract_result)
                generator_request["abstract_class_path"] = abstract_result["generated_files"][0]
                generator_request["abstract_class_source"] = "path"
                # Fresh only if this run produced the file, not a replay of an earlier run.
                abstract_fresh = not abstract_result.get("replayed", False)

        generator = GeneratorFactory.create(generator_type)
        result = generator.generate(generator_request, config=config)

        if result.get("success") and inherited:
            path = generator_request.get("abstract_class_path") or generator_request.get("package_name")
            if path:
                register_artifact(self.artifact_registry, path, result["generator_key"],
                                  created_fresh=abstract_fresh)

        if result.get("success") and generator_request.get("scaffold"):
            result["scaffold_result"] = self._scaffold(generator_request["scaffold"], config)

        return self._wrap(generator_type, result)

    def compensate(self, generator_request: dict, result: dict) -> dict:
        """Saga compensation for one request. Releases this request's
        reference on its abstract class and removes the file only when the
        registry says this caller may (creator, last reference, not already
        deleted). Never touches an abstract class loaded from path/package."""
        output = result.get("output", result)
        key = output.get("generator_key")
        path = generator_request.get("abstract_class_path")
        if not key or not path:
            return {"released": False, "removed": False, "path": path}
        may_delete = release_artifact(self.artifact_registry, path, key)
        removed = False
        if may_delete and os.path.isfile(path):
            os.remove(path)
            removed = True
        return {"released": True, "removed": removed, "may_delete": may_delete, "path": path}

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _wrap(generator_type, output):
        return {"status": "success" if output.get("success") else output.get("status", "failed"),
                "generator_type": generator_type,
                "output": output}

    @staticmethod
    def _scaffold(scaffold_request: dict, config: dict) -> dict:
        from base_project_bootstrapper import ProjectBootstrapperFactory
        bootstrapper = ProjectBootstrapperFactory.create(scaffold_request, config)
        return bootstrapper.bootstrap(scaffold_request, config)
