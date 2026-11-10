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
from a2c_template_llm import build_template_llm, code_artifact_paths
from ai_dlc_pipeline import AIDLCPipelineOrchestrator, AIDLCStaticPipeline
from e2a_inmemory_adapters import InMemoryIdempotencyStore, InMemoryTransactionalStore

SECRET_PATTERNS = [
    ('aws access key', re.compile(r'AKIA[0-9A-Z]{16}')),
    ('private key', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')),
    ('anthropic key', re.compile(r'sk-ant-[A-Za-z0-9\-_]{20,}')),
    ('literal password', re.compile(r'(?i)(password|secret)\s*=\s*"[^"$\s]{6,}"')),
]
ENTRY_POINTS = {'run', 'execute', 'retrieve'}
SKIP_DIRS = {'.git', '.venv', 'node_modules', 'target', '.terraform', '__pycache__'}

# What each BasePipeline stage really does in a local build. The base class
# reports every stage that did not fail as PASSED; these notes keep the
# evidence honest.
STAGE_NOTES = {
    'static_security': 'checked: secret patterns in every project file; terraform fmt when terraform is installed',
    'test_execution': 'checked only with --run-tests; otherwise the project CI runs the tests',
    'scaffold_compliance': 'checked: required artifacts exist; generated agents keep the inherited entry point',
    'ragas_gate': 'not applicable: no RAG pipeline in a build',
    'artifact_compilation': 'not applicable: the project CI compiles',
    'dynamic_security': 'not applicable: the project CI scans the image (Trivy)',
    'deployment_rollout': 'not performed: no deployment in a local build',
}


class ProjectStaticPipeline(AIDLCStaticPipeline):
    """Phase C with real checks against the generated project. Only the
    protected stage hooks are overridden; run_pipeline() stays inherited."""

    def __init__(self, project_root: Path, language: str, cloud: str, run_tests: bool = False):
        super().__init__()
        self.project_root, self.language, self.cloud = Path(project_root), language, cloud
        self.run_tests = run_tests
        self.findings: List[str] = []

    def _add_iac_tests(self) -> None:
        """Terraform tests ship with the A2C template, so `terraform test`
        works on day zero (Phase B wrote infra/main.tf before Phase C)."""
        test = self.project_root / 'infra' / 'tests' / f'{self.cloud}.tftest.hcl'
        if (self.project_root / 'infra' / 'main.tf').is_file() and not test.exists():
            test.parent.mkdir(parents=True, exist_ok=True)
            test.write_text(read_template(f'terraform/tests/{self.cloud}.tftest.hcl'), encoding='utf-8')

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
    facts = _prepare(request, output)
    root, runtime, cloud = facts['project_root'], facts['runtime'], facts['cloud']
    ctx = request['context']
    llm = build_template_llm()
    pipeline = ProjectStaticPipeline(root, runtime, cloud, run_tests)
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
            'checked: project tests ran' if run_tests else STAGE_NOTES['test_execution'])),
        'findings': pipeline.findings,
        'errors': result.get('errors', []),
        'llm_usage': llm.usage_summary(),
    }
    if root.is_dir():
        out = root / 'docs' / 'aidlc' / 'build-report.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str) + '\n', encoding='utf-8')
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='aidlc-build', description=__doc__.split('\n')[0])
    parser.add_argument('--request', required=True, help='AIDLCPipelineRequest JSON file')
    parser.add_argument('--output', default='.', help='directory the project folder is created in')
    parser.add_argument('--run-tests', action='store_true', help='run the generated tests in Phase C')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.ERROR, force=True)
    if not args.verbose:
        logging.disable(logging.WARNING)
    request = json.loads(Path(args.request).read_text(encoding='utf-8'))
    report = build(request, Path(args.output), args.run_tests)
    print(json.dumps({k: report[k] for k in ('success', 'phase_reached', 'project_root',
                                             'critic_score', 'findings', 'errors', 'llm_usage')},
                     indent=2, default=str))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    sys.exit(main())
