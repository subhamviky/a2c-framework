from abc import ABC, abstractmethod

class BaseGeneratorAgent(ABC):
    generator_name = "BaseGeneratorAgent"
    idempotency = True
    APPROVED_RUNTIMES = ["python", "java", "node", "go"]
    APPROVED_GENERATOR_TYPES = ["e2a_abstract", "a2c_abstract", "e2a_inherited", "a2c_inherited"]
    PROMPT_DIR = "prompts/"

    def generate(self, request, config=None, **kwargs):
        # Simplified 12-step sequence
        if not self.validate_request(request, config, **kwargs):
            raise ValueError("Invalid request")

        if request.get("runtime") not in self.APPROVED_RUNTIMES:
            raise ValueError("Unsupported runtime")

        system_prompt = self.build_system_prompt(request, config, **kwargs)
        user_prompt = self.build_user_prompt(request, config, **kwargs)

        # Fake LLM call
        response = f"Generated {self.generator_name} output for {request.get('runtime')}"

        score = self.evaluate_output(response, request, config, **kwargs)
        if score < 0.75:
            response = self.fallback(request, config, **kwargs)

        files = self.write_output(response, request, config, **kwargs)
        return {"success": True, "generated_files": files, "critic_report": {"score": score}}

    @abstractmethod
    def validate_request(self, request, config=None, **kwargs): ...
    @abstractmethod
    def resolve_config(self, request, config=None, **kwargs): ...
    @abstractmethod
    def build_system_prompt(self, request, config=None, **kwargs): ...
    @abstractmethod
    def build_user_prompt(self, request, config=None, **kwargs): ...
    @abstractmethod
    def evaluate_output(self, response, request, config=None, **kwargs): ...
    @abstractmethod
    def write_output(self, response, request, config=None, **kwargs): ...

    def fallback(self, request, config=None, **kwargs):
        return f"Fallback regeneration for {self.generator_name}"
