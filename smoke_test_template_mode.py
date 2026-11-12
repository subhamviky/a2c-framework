"""Smoke test for A2C v1.1.0: G2C Java fix + compile-checking critic, P0 starter
files, the A2C template LLM and the `aidlc-build` CLI (Python and Java).
Needs e2a-framework installed (pip install) or E2A_REFERENCE_PATH set.
Run: python smoke_test_template_mode.py"""
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if os.getenv('E2A_REFERENCE_PATH'):
    sys.path.insert(0, os.environ['E2A_REFERENCE_PATH'])
logging.disable(logging.CRITICAL)

import generator_templates as T                                   # noqa: E402
from a2c_cli import build                                          # noqa: E402
from a2c_template_llm import build_template_llm, class_prefix, project_slug  # noqa: E402
from base_project_bootstrapper import ProjectBootstrapperFactory   # noqa: E402
from generator_critic_agent import GeneratorCriticAgent           # noqa: E402

ok = 0


def check(name, cond):
    global ok
    assert cond, name
    ok += 1
    print('PASS', name)


# ---- naming helpers
check('project_slug', project_slug('HelloLedgerService') == 'hello-ledger-service')
check('class_prefix', class_prefix('hello-ledger-service') == 'HelloLedgerService')

# ---- G2C Java: hooks match between base and subclass; the critic compiles
tmp = Path(tempfile.mkdtemp())
base = tmp / 'E2ABase.java'
base.write_text(T.e2a_abstract('java', 'com.acme.common'))
il = T.import_line('e2a_inherited', 'java', 'path', None, 'com.acme.common')
agent = T.inherited('e2a_inherited', 'java', 'PayAgent', il, package='com.acme.service')
check('java base declares camelCase hooks', 'protected abstract Object buildMessages' in base.read_text())
check('java subclass implements every hook', all(f'Object {h}(' in agent for h in T.java_hooks('e2a_inherited')))
critic = GeneratorCriticAgent({'critic_type': 'e2a_inherited'})
req = {'runtime': 'java', 'agent_name': 'PayAgent', 'abstract_class_path': str(base)}
if shutil.which('javac'):
    report = critic.review(agent, req)
    check('critic: generated java compiles and scores 1.0', report['score'] == 1.0 and 'compiles' in report['passed'])
    broken = agent.replace('protected Object fallback', 'protected Object fallbackX')
    report = critic.review(broken, req)
    check('critic: java that does not compile scores 0.0', report['score'] == 0.0
          and report['missing'][0].startswith('java compile error'))
else:
    print('SKIP java compile checks (no javac on PATH)')

# ---- P0 starters
out = Path(tempfile.mkdtemp())
py = {'source': 'inline', 'runtime': 'python', 'build_tool': 'poetry', 'platform': 'gcp',
      'project_name': 'Demo', 'package_name': 'demo', 'project_type': 'fastapi_microservice',
      'output_path': str(out), 'dependencies': ['uvicorn[standard]>=0.30',
                                                 'e2a-framework @ git+https://github.com/x/e2a.git@v1.1.0']}
r = ProjectBootstrapperFactory.create(py).bootstrap(py)
root = Path(r['project_root'])
check('P0 python: main.py, test, CI, devcontainer, compose',
      all((root / f).is_file() for f in ('src/demo/main.py', 'tests/test_health.py', '.github/workflows/ci.yml',
                                         '.devcontainer/devcontainer.json', 'docker-compose.yml')))
manifest = (root / 'pyproject.toml').read_text()
check('P0 python: constraints and extras kept', '"uvicorn" = { version = ">=0.30", extras = ["standard"] }' in manifest)
check('P0 python: git dependency becomes a Poetry git source',
      '"e2a-framework" = { git = "https://github.com/x/e2a.git", tag = "v1.1.0" }' in manifest)
check('P0 python: fastapi added for a fastapi_microservice', '"fastapi" = ">=0.111"' in manifest)
check('P0 python: Dockerfile installs without the root package and without curl',
      '--no-root' in (root / 'Dockerfile').read_text() and 'curl' not in (root / 'Dockerfile').read_text())
check('P0 python: the venv is built at the path it runs from (/app/.venv), so its scripts find their interpreter',
      'WORKDIR /build' not in (root / 'Dockerfile').read_text()
      and 'COPY --from=builder /app/.venv /app/.venv' in (root / 'Dockerfile').read_text())
jv = {'source': 'inline', 'runtime': 'java', 'build_tool': 'maven', 'platform': 'azure',
      'project_name': 'Ledger', 'group_id': 'com.acme', 'artifact_id': 'ledger', 'project_type': 'spring_boot',
      'output_path': str(out), 'dependencies': ['web', 'actuator']}
r = ProjectBootstrapperFactory.create(jv).bootstrap(jv)
root = Path(r['project_root'])
check('P0 java: Application, tests, CI, devcontainer',
      all((root / f).is_file() for f in ('src/main/java/com/acme/Application.java',
                                         'src/test/java/com/acme/ApplicationTests.java',
                                         'src/test/java/com/acme/HealthEndpointTests.java',
                                         '.github/workflows/ci.yml', '.devcontainer/devcontainer.json')))
skip = dict(py, project_name='NoStarter', package_name='nostarter', include_starter=False)
r = ProjectBootstrapperFactory.create(skip).bootstrap(skip)
check('P0: include_starter=False keeps the v1.0 output', not (Path(r['project_root']) / 'src/nostarter/main.py').exists())

# ---- template LLM routes every role
llm = build_template_llm()
check('template LLM registers G2C and A2C rules',
      {'g2c:e2a_inherited', 'a2c:iac', 'a2c:cicd', 'a2c:critic', 'a2c:codegen'} <= set(llm.rule_names()))

# ---- aidlc-build: Python and Java
for name, request in (
        ('python', {'tenant_id': 't1',
                    'context': {'source': 'inline', 'project_name': 'py-svc', 'package_name': 'py_svc',
                                'runtime': 'python', 'build_tool': 'poetry', 'platform': 'gcp',
                                'project_type': 'fastapi_microservice'},
                    'harness': {'generator_type': 'e2a_inherited', 'agent_name': 'DemoAgent',
                                'abstract_class_source': 'package', 'package_name': 'e2a_base'},
                    'prompt': {'user_prompt': 'demo'},
                    'a2c_sdlc': {'enabled': True, 'project_type': 'FastAPI Microservice',
                                 'target_cloud': 'gcp', 'mandatory_nfrs': ['Audit']}}),
        ('java', {'tenant_id': 't1',
                  'context': {'source': 'inline', 'project_name': 'java-svc', 'runtime': 'java',
                              'build_tool': 'maven', 'platform': 'azure', 'project_type': 'spring_boot',
                              'group_id': 'com.acme.demo', 'artifact_id': 'java-svc',
                              'dependencies': ['web', 'actuator']},
                  'harness': {'generator_type': 'e2a_inherited', 'agent_name': 'DemoAgent',
                              'abstract_class_source': 'generate'},
                  'prompt': {'user_prompt': 'demo'},
                  'a2c_sdlc': {'enabled': True, 'project_type': 'Spring Boot',
                               'target_cloud': 'azure', 'mandatory_nfrs': ['Audit']}})):
    workdir = Path(tempfile.mkdtemp())
    report = build(json.loads(json.dumps(request)), workdir)
    check(f'aidlc-build {name}: E2A_VERIFIED with critic 1.0',
          report['success'] and report['phase_reached'] == 'E2A_VERIFIED' and report['critic_score'] == 1.0)
    root = Path(report['project_root'])
    check(f'aidlc-build {name}: infra, tests, delivery workflow, spec, build report',
          all((root / f).is_file() for f in ('infra/main.tf', '.github/workflows/a2c-ci.yml',
                                             'docs/a2c/spec.md', 'docs/aidlc/build-report.json'))
          and any((root / 'infra' / 'tests').glob('*.tftest.hcl')))
    check(f'aidlc-build {name}: simulated LLM usage recorded', report['llm_usage']['calls'] >= 7)

# ---- Phase C has teeth: a planted secret fails the build
workdir = Path(tempfile.mkdtemp())
planted = workdir / 'leaky-svc'
(planted / 'src').mkdir(parents=True)
(planted / 'src' / 'settings.py').write_text('API = "sk-ant-' + 'a' * 30 + '"\n')
request = {'tenant_id': 't1',
           'context': {'source': 'inline', 'project_name': 'leaky-svc', 'package_name': 'leaky_svc',
                       'runtime': 'python', 'build_tool': 'poetry', 'platform': 'aws',
                       'project_type': 'fastapi_microservice'},
           'harness': {'generator_type': 'e2a_inherited', 'agent_name': 'LeakAgent',
                       'abstract_class_source': 'package', 'package_name': 'e2a_base'},
           'prompt': {'user_prompt': 'demo'},
           'a2c_sdlc': {'enabled': True, 'project_type': 'FastAPI Microservice', 'target_cloud': 'aws'}}
report = build(request, workdir)
check('Phase C: a secret in the project fails verification',
      not report['success'] and any('secret scan' in f for f in report['findings']))

print(f'\n{ok} checks passed')
