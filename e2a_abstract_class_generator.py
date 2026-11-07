"""E2AAbstractClassGenerator — generates the E2A base abstract class file
(G2C Framework Reference §5): five abstract classes with one public entry
point each (BaseLLMAgentService has two) and four foundation interfaces.
No P0 scaffold. Output: e2a_base.py | E2ABase.java | e2aBase.ts | e2a_base.go."""
from pathlib import Path

from base_generator_agent import BaseGeneratorAgent
import generator_templates as T


class E2AAbstractClassGenerator(BaseGeneratorAgent):
    generator_name = "E2AAbstractClassGenerator"
    generator_type = "e2a_abstract"
    critic_type = "e2a_abstract"

    def _validate_request(self, request, config=None, **kwargs):
        return "runtime" in request and "output_path" in request

    def _build_user_prompt(self, request, config=None, **kwargs):
        name = request.get('base_class_name')
        extra = request.get('abstract_methods') or []
        return (f"Generate the complete E2A base abstract class file for runtime "
                f"{request['runtime']} {request.get('runtime_version', '')}."
                + (f" Add a domain base class {name}" if name else '')
                + (f" with extra abstract methods {extra}." if extra else '.')
                + (f" Description: {request['class_description']}" if request.get('class_description') else '')
                + (f"\n{request['user_prompt']}" if request.get('user_prompt') else '')
                + "\nReturn only the source file.")

    def _evaluate_output(self, response, request, config=None, **kwargs):
        return self._critic_review(response, request, config)

    def _write_output(self, response, request, config=None, **kwargs):
        fname = T.ABSTRACT_FILES['e2a_abstract'][request["runtime"]]
        return [self._write_file(request['output_path'], fname, response)]

    def _existing_output(self, request, config=None):
        p = Path(request['output_path']) / T.ABSTRACT_FILES['e2a_abstract'][request['runtime']]
        return [str(p.resolve())] if p.is_file() else None

    def _template_output(self, request, config=None, **kwargs):
        return T.e2a_abstract(request.get('runtime', 'python'))
