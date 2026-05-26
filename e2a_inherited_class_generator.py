from base_generator_agent import BaseGeneratorAgent

class E2AInheritedClassGenerator(BaseGeneratorAgent):
    generator_name = "E2AInheritedClassGenerator"

    def validate_request(self, request, config=None, **kwargs):
        return "runtime" in request and "agent_name" in request and "output_path" in request

    def resolve_config(self, request, config=None, **kwargs):
        return request

    def build_system_prompt(self, request, config=None, **kwargs):
        return "System prompt for E2A inherited class"

    def build_user_prompt(self, request, config=None, **kwargs):
        return f"Generate inherited E2A agent {request['agent_name']}"

    def evaluate_output(self, response, request, config=None, **kwargs):
        return 1.0

    def write_output(self, response, request, config=None, **kwargs):
        return [f"{request['output_path']}/{request['agent_name']}.py"]
