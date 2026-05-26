from base_generator_agent import BaseGeneratorAgent

class E2AAbstractClassGenerator(BaseGeneratorAgent):
    generator_name = "E2AAbstractClassGenerator"

    def validate_request(self, request, config=None, **kwargs):
        return "runtime" in request and "output_path" in request

    def resolve_config(self, request, config=None, **kwargs):
        return request

    def build_system_prompt(self, request, config=None, **kwargs):
        return "System prompt for E2A abstract class"

    def build_user_prompt(self, request, config=None, **kwargs):
        return "User prompt for E2A abstract class"

    def evaluate_output(self, response, request, config=None, **kwargs):
        return 1.0

    def write_output(self, response, request, config=None, **kwargs):
        fname = {"python": "e2a_base.py", "java": "E2ABase.java",
                 "node": "e2aBase.ts", "go": "e2a_base.go"}.get(request["runtime"], "e2a_base.py")
        return [f"{request['output_path']}/{fname}"]
