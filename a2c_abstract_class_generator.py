from base_generator_agent import BaseGeneratorAgent

class A2CAbstractClassGenerator(BaseGeneratorAgent):
    generator_name = "A2CAbstractClassGenerator"

    def validate_request(self, request, config=None, **kwargs):
        return "runtime" in request and "output_path" in request

    def resolve_config(self, request, config=None, **kwargs):
        return request

    def build_system_prompt(self, request, config=None, **kwargs):
        return "System prompt for A2C abstract class"

    def build_user_prompt(self, request, config=None, **kwargs):
        return "User prompt for A2C abstract class"

    def evaluate_output(self, response, request, config=None, **kwargs):
        return 1.0

    def write_output(self, response, request, config=None, **kwargs):
        return [f"{request['output_path']}/a2c_base.py"]
