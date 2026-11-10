"""inherited_generator.py — shared phases of the inherited-class generators
(G2C Framework Reference §7.2, §8): one call from request to an inherited
class inside a P0-scaffolded project.

  Setup                 1–4   resolve · validate · policy · claim   (base)
  Abstract resolution   5–6   generate | path | package; base copied into
                              the project's common/ directory      (_prepare)
  P0 scaffold           7–8   ProjectBootstrapperFactory.create(scaffold)
                              .bootstrap() when request['scaffold'] is set
  Logic generation      9–11  prompts with the base as context; _infer()
  Quality gate          12    GeneratorCriticAgent
  Output                13–14 class file written into the scaffold; SLO; log

The abstract-class chain and P0 run after the claim, so a replay of a
settled generator_key returns the stored result without generating or
scaffolding again (the idempotent no-op). Both steps are idempotent in
their own right (claim or directory check), so they are not treated as the
first side effect: a later model failure still settles retryable.
"""
import shutil
from pathlib import Path

from base_generator_agent import BaseGeneratorAgent
import generator_templates as T

_BUILD_TOOL = {'python': 'poetry', 'java': 'maven', 'node': 'npm', 'go': 'go_modules'}
_FINAL = ('failed_final', 'conflict', 'critic_threshold_not_met')


class BaseInheritedClassGenerator(BaseGeneratorAgent):
    """Intermediate base for E2A/A2C inherited generators. Not registered."""
    kind = ''                           # 'e2a_inherited' | 'a2c_inherited'

    def _validate_request(self, request, config=None, **kwargs):
        if not all(k in request for k in ("runtime", "agent_name", "output_path")):
            return False
        src = request.get('abstract_class_source', 'generate')
        if src == 'path' and not request.get('abstract_class_path'):
            return False
        if src == 'package' and not request.get('package_name'):
            return False
        return src in ('generate', 'path', 'package')

    # ----------------------------------------------------- phases 5–8
    def _prepare(self, request, config=None, **kwargs):
        config = config or {}
        request.setdefault('abstract_class_source', 'generate')
        if request['abstract_class_source'] == 'generate':
            abort = self._generate_abstracts(request, config)
            if abort:
                return abort
        out = {'result': {}, 'files_before': []}
        if request.get('scaffold') is not None:
            sr = self._scaffold(request, config)
            out['result']['scaffold_result'] = sr
            if not sr.get('success'):
                return {'result': out['result'], 'abort': {
                    'status': 'scaffold_failed', 'errors': sr.get('errors') or [sr.get('status')],
                    'retryable': sr.get('status') not in ('conflict', 'failed_final')}}
            request['project_root'] = sr.get('project_root')
            self._place_java_abstracts(request)
        root = request.get('project_root')
        if root and request.get('java_common_package'):
            # Java abstracts already live in the Maven source tree.
            out['files_before'] += [str(Path(request[k]).resolve())
                                    for k in ('e2a_abstract_class_path', 'abstract_class_path')
                                    if request.get(k) and Path(request[k]).is_file()]
        elif root and request['abstract_class_source'] == 'path':
            for key in ('e2a_abstract_class_path', 'abstract_class_path'):
                src = request.get(key)
                if src and Path(src).is_file():
                    dst = Path(root) / 'common' / Path(src).name
                    if dst.resolve() != Path(src).resolve():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(src, dst)
                    out['files_before'].append(str(dst.resolve()))
        return out

    def _generate_abstracts(self, request, config):
        """Run the abstract generator(s) first; the result becomes a 'path'
        source. The abstract output is shared across projects of a tenant
        (output_path is excluded from its fingerprint), so several
        generator_keys may reference one generated file."""
        from e2a_abstract_class_generator import E2AAbstractClassGenerator
        from a2c_abstract_class_generator import A2CAbstractClassGenerator
        base_dir = config.get('abstract_class_output_path') or \
            str(Path(request['output_path']) / 'common')
        common = {k: request[k] for k in ('runtime', 'runtime_version', 'platform', 'tenant_id',
                                         'deadline_ms', 'model_id', 'domain') if k in request}
        common.update(output_path=base_dir, fingerprint_exclude=['output_path'])
        steps = [(E2AAbstractClassGenerator, {**request.get('abstract_class_config', {}),
                                             **common, 'generator_type': 'e2a_abstract'})]
        if self.kind == 'a2c_inherited':
            steps.append((A2CAbstractClassGenerator, {**common, 'generator_type': 'a2c_abstract',
                                                     'abstract_class_source': 'path'}))
        prev = None
        for gen_cls, sub in steps:
            if prev:
                sub['abstract_class_path'] = prev
            r = gen_cls(config).generate(sub, config)
            if not r.get('success'):
                return {'abort': {'status': r.get('status', 'failed'), 'errors': r.get('errors', []),
                                  'retryable': r.get('status') not in _FINAL}}
            if prev is None and self.kind == 'a2c_inherited':
                request['e2a_abstract_class_path'] = r['generated_files'][0]
            prev = r['generated_files'][0]
            request['abstract_class_generated_fresh'] = not r.get('replayed', False)
        request['abstract_class_path'] = prev
        request['abstract_class_source'] = 'path'
        return None

    def _place_java_abstracts(self, request):
        """Java only: copy the generated abstract files into the Maven source
        tree as <group_id>.common, so the scaffolded project compiles."""
        sc = request.get('scaffold_resolved') or {}
        gid, root = sc.get('group_id'), request.get('project_root')
        if request.get('runtime') != 'java' or not (gid and root):
            return
        package = f'{gid}.common'
        target = Path(root) / 'src' / 'main' / 'java' / Path(*package.split('.'))
        for key in ('e2a_abstract_class_path', 'abstract_class_path'):
            src = request.get(key)
            if not (src and Path(src).is_file()):
                continue
            text = Path(src).read_text(encoding='utf-8')
            lines = text.splitlines()
            if lines and lines[0].startswith('package '):
                lines[0] = f'package {package};'
            else:
                lines = [f'package {package};', ''] + lines
            dst = target / Path(src).name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            request[key] = str(dst.resolve())
        request['java_common_package'] = package
        request['java_package'] = f'{gid}.service'

    def _scaffold(self, request, config):
        """P0 inline. Missing scaffold fields default from the generator
        request; runtime-specific identity (package_name, group_id,
        artifact_id, project_type for Java) comes from request['scaffold']."""
        from base_project_bootstrapper import ProjectBootstrapperFactory
        sc = dict(request['scaffold'])
        rt = request.get('runtime', 'python')
        sc.setdefault('runtime', rt)
        sc.setdefault('platform', request.get('platform', 'standalone'))
        sc.setdefault('build_tool', _BUILD_TOOL.get(rt))
        sc.setdefault('project_name', request['agent_name'] + 'Service')
        if rt == 'python':
            sc.setdefault('package_name', T.snake(sc['project_name']))
        sc.setdefault('output_path', request['output_path'])
        if request.get('tenant_id'):
            sc.setdefault('tenant_id', request['tenant_id'])
        try:
            bootstrapper = ProjectBootstrapperFactory.create(sc, config)
        except ValueError as e:
            return {'success': False, 'status': 'failed_final', 'errors': [str(e)]}
        request['scaffold_resolved'] = sc
        return bootstrapper.bootstrap(sc, config)

    # ----------------------------------------------------- phases 9–14
    def _abstract_context(self, request):
        if request.get('abstract_class_source') == 'package':
            return f"# Package: {request.get('package_name')} -- import from the installed library"
        parts = []
        for key in ('e2a_abstract_class_path', 'abstract_class_path'):
            p = request.get(key)
            if p and Path(p).is_file():
                parts.append(Path(p).read_text(encoding='utf-8')[:20000])
        return '\n\n'.join(parts)

    def _build_user_prompt(self, request, config=None, **kwargs):
        base = 'SDLCAssistantAgent' if self.kind == 'a2c_inherited' else 'the E2A base class'
        package = (f"Java package: {request['java_package']}\n"
                   if request.get('java_package') else '')
        return (f"Generate class {request['agent_name']} extending {base} for runtime "
                f"{request['runtime']}. Import line: {self._import(request)}\n{package}"
                f"Domain: {request.get('domain', 'general')}. Requirement: {request.get('user_prompt', '')}\n"
                f"Mandatory NFRs: {request.get('mandatory_nfrs', [])}\n"
                "Return only the source file.")

    def _evaluate_output(self, response, request, config=None, **kwargs):
        return self._critic_review(response, request, config)

    def _write_output(self, response, request, config=None, **kwargs):
        rt, agent = request['runtime'], request['agent_name']
        root = request.get('project_root')
        sc = request.get('scaffold_resolved') or {}
        if rt == 'python':
            pkg = sc.get('package_name')
            rel = f"src/{pkg}/agents/{T.snake(agent)}.py" if root and pkg else f"{T.snake(agent)}.py"
        elif rt == 'java':
            gid = sc.get('group_id')
            rel = (f"src/main/java/{gid.replace('.', '/')}/service/{agent}.java"
                   if root and gid else f"{agent}.java")
        elif rt == 'node':
            rel = f"src/agents/{agent}.ts" if root else f"{agent}.ts"
        else:
            rel = f"internal/agents/{T.snake(agent)}.go" if root else f"{T.snake(agent)}.go"
        return [self._write_file(root or request['output_path'], rel, response)]

    def _template_output(self, request, config=None, **kwargs):
        return T.inherited(self.kind, request.get('runtime', 'python'), request['agent_name'],
                           self._import(request), request.get('mandatory_nfrs'),
                           package=request.get('java_package'))

    def _import(self, request):
        return T.import_line(self.kind, request.get('runtime', 'python'),
                             request.get('abstract_class_source', 'generate'),
                             request.get('package_name'), request.get('java_common_package'))
