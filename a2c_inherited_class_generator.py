from base_generator_agent import BaseGeneratorAgent

class A2CInheritedClassGenerator(BaseGeneratorAgent):
    generator_name = "A2CInheritedClassGenerator"

    def validate_request(self, request, config=None, **kwargs):
        return "runtime" in request and "agent_name" in request and "output_path" in request

    def resolve_config(self, request, config=None, **kwargs):
        return request

    def build_system_prompt(self, request, config=None, **kwargs):
        return "System prompt for A2C inherited class"

    def build_user_prompt(self, request, config=None, **kwargs):
        return f"Generate inherited A2C agent {request['agent_name']}"

    def evaluate_output(self, response, request, config=None, **kwargs):
        return 1.0

    def write_output(self, response, request, config=None, **kwargs):
        return [f"{request['output_path']}/{request['agent_name']}.py"]
