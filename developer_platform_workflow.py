# developer_platform_workflow.py

from generator_factory import GeneratorFactory

class DeveloperPlatformWorkflow:
    """
    Orchestrates generator execution for developer platform use cases.
    Wraps GeneratorFactory and exposes a unified generate() entrypoint.
    """

    def __init__(self):
        pass

    def generate(self, generator_request: dict, scaffold_config: dict = None):
        # Step 1: Resolve generator type
        generator_type = generator_request.get("generator_type")
        generator = GeneratorFactory.create(generator_type)

        # Step 2: Run generation
        result = generator.generate(generator_request, config=scaffold_config)

        # Step 3: Return structured result
        return {
            "status": "success",
            "generator_type": generator_type,
            "output": result
        }
