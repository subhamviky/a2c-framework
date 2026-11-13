"""a2c_cli.py — `aidlc-build`: build one service through the E2A AI-DLC pipeline.

    aidlc-build --request aidlc-request.json [--output .] [--run-tests]

One command runs AIDLCPipelineOrchestrator.execute_pipeline():
  Phase A  G2C class generation + P0 scaffold (inline)
  Phase B  A2C SDLCWorkflow: spec, Terraform, CI/CD, NFR code, critic
  Phase C  E2A static verification (ProjectStaticPipeline below)

The model boundary is A2C template mode (build_template_llm): deterministic,
offline, no account. The request file is an AIDLCPipelineRequest:
  {"tenant_id", "context": <P0 ScaffoldRequest>, "harness": <G2C request>,
   "prompt": {"user_prompt"}, "a2c_sdlc": {enabled, project_type,
   mandatory_nfrs, target_cloud}}
"""
import argparse
import ast
import compileall
import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from a2c_assets import read_template
from a2c_base import MANDATORY_NFRS
import g2c_java12
import g2c_v12

E2A_REF = 'v1.2.2'          # the E2A version this A2C release generates for (its own pin)
from a2c_contracts import contracts_from
from a2c_layout import LAYOUTS, move_workflows
from a2c_upgrade import UpgradeError, clean_request, upgrade, write_manifest
from a2c_settings import normalize as normalize_settings, terraform as settings_terraform
from a2c_template_llm import SETTINGS_PLACEHOLDERS, build_template_llm, code_artifact_paths
from ai_dlc_pipeline import AIDLCPipelineOrchestrator, AIDLCStaticPipeline
from e2a_inmemory_adapters import InMemoryIdempotencyStore, InMemoryTransactionalStore

from e2a.conformance import check_paths, failed          # v1.2.1 (C-04): Phase C uses E2A's checks
from e2a.release import SECRET_PATTERNS, load_cases        # one list of secret patterns, E2A's
from a2c_evaluation import normalize_evaluation
ENTRY_POINTS = {'run', 'execute', 'retrieve'}
SKIP_DIRS = {'.git', '.venv', 'node_modules', 'target', '.terraform', '__pycache__'}

# What each BasePipeline stage really does in a local build. The base class
# reports every stage that did not fail as PASSED; these notes keep the
# evidence honest.
STAGE_NOTES = {
    'static_security': 'checked: secret patterns in every project file; terraform fmt when terraform is installed',
    'test_execution': 'checked only with --run-tests; otherwise the project CI runs the tests',
    'scaffold_compliance': 'checked: required artifacts exist; generated agents keep the inherited entry point',
    'ragas_gate': 'not applicable: no evaluation set declared (a2c_sdlc.evaluation)',
    'artifact_compilation': 'not applicable: the project CI compiles (Python on E2A v1.2: compiled in scaffold_compliance)',
    'dynamic_security': 'not applicable: the project CI scans the image (Trivy)',
    'deployment_rollout': 'not performed: no deployment in a local build',
}


class ProjectStaticPipeline(AIDLCStaticPipeline):
    """Phase C with real checks against the generated project. Only the
    protected stage hooks are overridden; run_pipeline() stays inherited."""

    def __init__(self, project_root: Path, language: str, cloud: str, run_tests: bool = False,
                 settings: List[Dict[str, Any]] = (), e2a_contract: str = '1.1',
                 evaluation: Dict[str, Any] = None):
        super().__init__()
        self.project_root, self.language, self.cloud = Path(project_root), language, cloud
        self.settings = list(settings)
        self.e2a_contract, self.evaluation = e2a_contract, evaluation
        self.evaluation_cases: Dict[str, int] = {}
        self.run_tests = run_tests
        self.findings: List[str] = []

    def _add_iac_tests(self) -> None:
        """Terraform tests ship with the A2C template, so `terraform test`
        works on day zero (Phase B wrote infra/main.tf before Phase C)."""
        test = self.project_root / 'infra' / 'tests' / f'{self.cloud}.tftest.hcl'
        if (self.project_root / 'infra' / 'main.tf').is_file() and not test.exists():
            test.parent.mkdir(parents=True, exist_ok=True)
            values = settings_terraform(self.cloud, self.settings)      # v1.2 (A-3): one assertion per setting
            text = read_template(f'terraform/tests/{self.cloud}.tftest.hcl')
            for key in SETTINGS_PLACEHOLDERS:
                text = text.replace('{{' + key + '}}', values.get(key, ''))
            test.write_text(text, encoding='utf-8')

    def _files(self):
        for path in self.project_root.rglob('*'):
            if path.is_file() and not (SKIP_DIRS & set(path.parts)):
                yield path

    def _run_static_security_scans(self, config, **kwargs) -> bool:
        for path in self._files():
            try:
                text = path.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue
            for name, pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    self.findings.append(f'secret scan: {name} in {path.relative_to(self.project_root)}')
        if shutil.which('terraform') and (self.project_root / 'infra').is_dir():
            proc = subprocess.run(['terraform', 'fmt', '-check', '-recursive'],
                                  cwd=self.project_root / 'infra', capture_output=True, text=True)
            if proc.returncode != 0:
                self.findings.append(f'terraform fmt: {proc.stdout.strip() or proc.stderr.strip()}')
        return not self.findings

    def _verify_scaffold_contracts(self, config, **kwargs) -> bool:
        self._add_iac_tests()
        required = ['.github/workflows/ci.yml', '.github/workflows/a2c-ci.yml',
                    'infra/main.tf', 'docs/a2c/spec.md', 'Dockerfile']
        required.append('pyproject.toml' if self.language == 'python' else 'pom.xml')
        missing = [r for r in required if not (self.project_root / r).is_file()]
        self.findings += [f'missing artifact: {m}' for m in missing]
        if self.language == 'python' and self.e2a_contract == '1.2':
            self._check_v12_project()                 # v1.2.1 (C-04): E2A's conformance, strict, and compile
            return not self.findings
        for path in self._files():
            if path.suffix == '.py' and '/agents/' in path.as_posix():
                tree = ast.parse(path.read_text(encoding='utf-8'))
                for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
                    own = {f.name for f in cls.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
                    if own & ENTRY_POINTS:
                        self.findings.append(f'{path.name}: {cls.name} overrides {sorted(own & ENTRY_POINTS)}')
            elif path.suffix == '.java' and '/service/' in path.as_posix():
                text = path.read_text(encoding='utf-8')
                if re.search(r'extends\s+Base\w+', text) and re.search(
                        r'(?m)^\s*public\s+[\w<>, ]+\s+(run|execute|retrieve)\s*\(', text):
                    self.findings.append(f'{path.name}: overrides a template-method entry point')
        return not self.findings

    def _check_v12_project(self) -> None:
        src = self.project_root / 'src'
        findings = check_paths([str(src)]) if src.is_dir() else []
        if failed(findings, strict=True):
            self.findings += [f'conformance: {f}' for f in findings if f.rule in ('R1', 'R2', 'D1')]
        if src.is_dir() and not compileall.compile_dir(str(src), quiet=1):
            self.findings.append('compile: src/ does not byte-compile')
        for key in ('set', 'redteam'):                # the cases are scored by the project CI, not here
            name = (self.evaluation or {}).get(key)
            if not name:
                continue
            try:
                self.evaluation_cases[name] = len(load_cases(self.project_root / name))
            except ValueError as error:
                self.findings.append(f'evaluation: {error}')

    def _execute_test_suite(self, config, **kwargs) -> bool:
        if not self.run_tests:
            return True
        if self.language == 'python':
            cmd = 'poetry install --no-interaction -q && poetry run pytest -q'
        else:
            cmd = 'mvn -B -q verify'
        proc = subprocess.run(cmd, shell=True, cwd=self.project_root, capture_output=True, text=True)
        if proc.returncode != 0:
            self.findings.append('tests failed:\n' + (proc.stdout + proc.stderr)[-2000:])
        return proc.returncode == 0


def _prepare(request: Dict[str, Any], output: Path) -> Dict[str, Any]:
    """Resolve paths and give the template LLM the facts it reads."""
    ctx, harness = request.setdefault('context', {}), request.setdefault('harness', {})
    a2c = request.setdefault('a2c_sdlc', {})
    runtime = ctx.get('runtime') or harness.get('runtime', 'python')
    ctx.setdefault('runtime', runtime)
    harness.setdefault('runtime', runtime)
    harness.setdefault('output_path', str(output))
    ctx.setdefault('output_path', str(output))
    cloud = a2c.get('target_cloud') or ctx.get('platform', 'aws')
    ctx.setdefault('platform', cloud)
    harness.setdefault('platform', cloud)
    # v1.2 (G-3): Python code targets E2A v1.2 unless the request says 1.1; Java has no v1.2 runtime yet
    harness.setdefault('e2a_contract', '1.2' if runtime == 'python'
                       and harness.get('generator_type', 'e2a_inherited') == 'e2a_inherited' else '1.1')
    if harness['e2a_contract'] == '1.2' and runtime not in ('python', 'java'):
        raise ValueError(f'e2a_contract 1.2 is available for Python and Java (e2a-java), not {runtime}')
    if harness['e2a_contract'] == '1.2' and runtime == 'java':
        g2c_java12.normalize(harness)               # D-01: agents / workflow / governance, e2a-java's stages
        deps = ctx.setdefault('dependencies', [])   # Maven coordinates (P-5): the generated code and tests
        v = g2c_java12.E2A_JAVA_VERSION
        for coord in (f'com.subhamviky.e2a:e2a-core:{v}', f'com.subhamviky.e2a:e2a-test:{v}@test'):
            if coord not in deps:
                deps.append(coord)
        ctx['e2a_java'] = v                         # P0: the CI and the Dockerfile install e2a-java first
    elif harness['e2a_contract'] == '1.2':
        g2c_v12.normalize(harness)                  # agents / workflow / governance checked up front
        harness['project_package'] = ctx.get('package_name')
        deps = ctx.setdefault('dependencies', [])   # the generated code and tests import e2a
        if not any(str(d).replace('_', '-').startswith('e2a-framework') for d in deps):
            deps.append(f'e2a-framework @ git+https://github.com/subhamviky/e2a-framework.git@{E2A_REF}')
    # v1.2 (A-3): app settings are declared once, in a2c_sdlc; P0 and A2C both read them
    ctx['settings'] = normalize_settings(a2c.get('settings') or ctx.get('settings'))
    a2c['settings'] = ctx['settings']
    # v1.2.1 (C-04, D-2): evaluation sets, and E2A's release gate in the CI of an E2A v1.2 service
    evaluation = normalize_evaluation(a2c.get('evaluation') or ctx.get('evaluation'))
    if evaluation and (runtime != 'python' or harness['e2a_contract'] != '1.2'):
        raise ValueError('a2c_sdlc.evaluation needs a Python service on E2A v1.2: the gate is '
                         'e2a.release.ProjectReleaseGate')
    if evaluation:
        ctx['evaluation'] = a2c['evaluation'] = evaluation
    ctx['release_gate'] = harness['e2a_contract'] == '1.2' and runtime == 'python'
    # v1.2 (A-5): contracts are read (and checked) once, relative to the working directory or the request
    base = Path(request.get('_request_dir', '.'))
    ctx['contract_schemas'] = [{'path': str(p), 'schema': c.schema}
                               for p, c in zip(a2c.get('contracts', []), contracts_from(a2c.get('contracts', []), base))]
    nfrs = list(dict.fromkeys(a2c.get('mandatory_nfrs', []) + MANDATORY_NFRS))
    lines = [request.get('prompt', {}).get('user_prompt', '').strip(),
             f"Project: {ctx['project_name']}; Cloud: {cloud}",
             f'Mandatory NFRs: {nfrs}']
    if runtime == 'java' and ctx.get('group_id'):
        lines.append(f"Java package: {ctx['group_id']}.generated")
    request.setdefault('prompt', {})['user_prompt'] = '\n'.join(l for l in lines if l)
    return {'runtime': runtime, 'cloud': cloud,
            'project_root': Path(ctx['output_path']).resolve() / ctx['project_name']}


def build(request: Dict[str, Any], output: Path, run_tests: bool = False) -> Dict[str, Any]:
    original = clean_request(request)                 # v1.2 (A-6): what the manifest records
    facts = _prepare(request, output)
    root, runtime, cloud = facts['project_root'], facts['runtime'], facts['cloud']
    ctx = request['context']
    llm = build_template_llm()
    pipeline = ProjectStaticPipeline(root, runtime, cloud, run_tests, request['context'].get('settings', []),
                                     request['harness'].get('e2a_contract', '1.1'), ctx.get('evaluation'))
    config = {
        'llm_service': llm,
        'idempotency_store': InMemoryIdempotencyStore(),
        'artifact_store': InMemoryTransactionalStore(),
        'static_pipeline': pipeline,
        'tenant_id': request.get('tenant_id', 'local'),
        'abstract_class_output_path': str(Path(output).resolve() / '.aidlc' / 'g2c-cache'),
        'a2c_artifact_paths': code_artifact_paths(runtime, ctx['project_name'],
                                                  ctx.get('package_name'), ctx.get('group_id')),
    }

    result = AIDLCPipelineOrchestrator(config=config).execute_pipeline(request, config)
    report = {
        'success': bool(result.get('success')),
        'phase_reached': result.get('phase_reached'),
        'project_root': str(root),
        'critic_score': ((result.get('sdlc_result') or {}).get('critic_report') or {}).get('score'),
        'g2c_files': (result.get('generator_result') or {}).get('generated_files', []),
        'pipeline_stages': (result.get('pipeline_report') or {}).get('stages', {}),
        'stage_notes': dict(STAGE_NOTES, test_execution=(
            'checked: project tests ran' if run_tests else STAGE_NOTES['test_execution']), **(
            {'scaffold_compliance': 'checked: required artifacts exist; e2a.conformance (strict) over src/; '
                                    'src/ byte-compiles'} if pipeline.e2a_contract == '1.2' and runtime == 'python'
            else {}), **({'ragas_gate': 'checked: the evaluation set is well formed ('
                          f'{pipeline.evaluation_cases}); the project CI scores it on every commit'}
                         if ctx.get('evaluation') else {})),
        'findings': pipeline.findings,
        'evaluation_cases': pipeline.evaluation_cases,
        'errors': result.get('errors', []),
        'llm_usage': llm.usage_summary(),
    }
    layout = request['context'].get('repository_layout', 'single')
    if root.is_dir() and layout == 'monorepo':           # v1.2 (P-6): workflows run from the repository root
        report['root_workflows'] = move_workflows(Path(output), request['context']['project_name'])
    if root.is_dir() and report['success']:              # v1.2 (A-6): the manifest --upgrade works from
        report['manifest'] = str(write_manifest(Path(output), request['context']['project_name'], original))
    if root.is_dir():
        out = root / 'docs' / 'aidlc' / 'build-report.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str) + '\n', encoding='utf-8')
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='aidlc-build', description=__doc__.split('\n')[0])
    parser.add_argument('--request', help='AIDLCPipelineRequest JSON file (optional with --upgrade: the manifest has it)')
    parser.add_argument('--upgrade', metavar='PROJECT_DIR',
                        help='bring an existing scaffold to this A2C version (replaces untouched files, '
                             'writes a2c-upgrade.patch for files you changed)')
    parser.add_argument('--baseline', metavar='DIR',
                        help='with --upgrade: the same request built by the A2C version that scaffolded the project')
    parser.add_argument('--output', default='.', help='directory the project folder is created in')
    parser.add_argument('--run-tests', action='store_true', help='run the generated tests in Phase C')
    parser.add_argument('--repository-layout', choices=LAYOUTS,
                        help='monorepo: move the generated workflows to the repository root, scoped to the service')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.ERROR, force=True)
    if not args.verbose:
        logging.disable(logging.WARNING)
    if args.upgrade:
        return _upgrade(args)
    if not args.request:
        parser.error('--request is required (except with --upgrade)')
    request = json.loads(Path(args.request).read_text(encoding='utf-8'))
    request['_request_dir'] = str(Path(args.request).resolve().parent)
    if args.repository_layout:
        request.setdefault('context', {})['repository_layout'] = args.repository_layout
    try:
        report = build(request, Path(args.output), args.run_tests)
    except ValueError as error:                       # a declaration that cannot be generated
        print(json.dumps({'success': False, 'errors': [str(error)]}, indent=2))
        return 1
    print(json.dumps({k: report[k] for k in ('success', 'phase_reached', 'project_root', 'critic_score',
                                             'findings', 'errors', 'llm_usage', 'root_workflows') if k in report},
                     indent=2, default=str))
    return 0 if report['success'] else 1


def _upgrade(args) -> int:
    project = Path(args.upgrade).resolve()
    request = json.loads(Path(args.request).read_text(encoding='utf-8')) if args.request else None
    if request is not None and args.repository_layout:
        request.setdefault('context', {})['repository_layout'] = args.repository_layout

    def rebuild(req, output):
        req['_request_dir'] = str(project.parent)          # contracts resolve from the repository root
        return build(req, output)

    try:
        report = upgrade(project, rebuild, request, Path(args.baseline).resolve() if args.baseline else None)
    except UpgradeError as error:
        print(json.dumps({'success': False, 'error': str(error)}, indent=2))
        return 1
    print(json.dumps({'success': True, **{k: v for k, v in report.items() if k != 'unchanged'},
                      'unchanged': len(report['unchanged'])}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
