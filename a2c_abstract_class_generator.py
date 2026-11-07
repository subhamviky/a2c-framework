"""A2CAbstractClassGenerator — generates the A2C base file (G2C Framework
Reference §6): DevRequest, SDLCAssistantAgent, the specialist agents,
CodeCriticAgent and SDLCWorkflow, extending the E2A base. The E2A base is
always given to the model as context; when abstract_class_source is
'generate' (the default) and no path is supplied, it is generated first.
No P0 scaffold."""
from pathlib import Path

from base_generator_agent import BaseGeneratorAgent
import generator_templates as T


class A2CAbstractClassGenerator(BaseGeneratorAgent):
    generator_name = "A2CAbstractClassGenerator"
    generator_type = "a2c_abstract"
    critic_type = "a2c_abstract"

    def _validate_request(self, request, config=None, **kwargs):
        return "runtime" in request and "output_path" in request

    def _prepare(self, request, config=None, **kwargs):
        """Resolve the E2A base used as context (generate | path | package)."""
        src = request.get('abstract_class_source', 'generate')
        if src == 'generate' and not request.get('abstract_class_path'):
            from e2a_abstract_class_generator import E2AAbstractClassGenerator
            sub = {k: request[k] for k in ('runtime', 'runtime_version', 'platform', 'tenant_id',
                                          'deadline_ms', 'model_id', 'domain') if k in request}
            sub.update(generator_type='e2a_abstract', output_path=request['output_path'],
                       fingerprint_exclude=['output_path'])
            r = E2AAbstractClassGenerator(config).generate(sub, config)
            if not r.get('success'):
                return {'abort': {'status': r.get('status', 'failed'), 'errors': r.get('errors', []),
                                  'retryable': r.get('status') not in ('failed_final', 'conflict',
                                                                      'critic_threshold_not_met')}}
            request['abstract_class_path'] = r['generated_files'][0]
            request['abstract_class_source'] = 'path'
        return {}

    def _abstract_context(self, request):
        if request.get('abstract_class_source') == 'package':
            return f"# Package: {request.get('package_name')} -- import from installed library"
        p = request.get('abstract_class_path')
        return Path(p).read_text(encoding='utf-8')[:20000] if p and Path(p).exists() else ''

    def _build_user_prompt(self, request, config=None, **kwargs):
        return (f"Generate the A2C base file for runtime {request['runtime']}: DevRequest, "
                "SDLCAssistantAgent, RequirementsAgent, CodeGenAgent, IaCAgent, CICDAgent, "
                "CodeCriticAgent, SDLCWorkflow and the validation service, extending the E2A base "
                "given in the system prompt." + (f"\n{request['user_prompt']}" if request.get('user_prompt') else '')
                + "\nReturn only the source file.")

    def _evaluate_output(self, response, request, config=None, **kwargs):
        return self._critic_review(response, request, config)

    def _write_output(self, response, request, config=None, **kwargs):
        fname = T.ABSTRACT_FILES['a2c_abstract'][request["runtime"]]
        return [self._write_file(request['output_path'], fname, response)]

    def _existing_output(self, request, config=None):
        p = Path(request['output_path']) / T.ABSTRACT_FILES['a2c_abstract'][request['runtime']]
        return [str(p.resolve())] if p.is_file() else None

    def _template_output(self, request, config=None, **kwargs):
        return T.a2c_abstract(request.get('runtime', 'python'))
