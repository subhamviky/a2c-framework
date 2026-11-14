"""A2C v1.4 (hub design note MP-03, P27): a generated Python service binds its model from a
profile (e2a.bindings); nothing in it constructs a model service by name.

B-1 the composition root is generated · B-2 the default profile is E2A's "simulated" ·
B-3 a request names another profile and the package that provides it · B-4 the generated
tests pass · B-5 one request runs through the bound model."""
import importlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import g2c_v12
from a2c_cli import E2A_REF, build

passed = 0
HERE = Path(__file__).resolve().parent


def check(name, ok):
    global passed
    print(('PASS ' if ok else 'FAIL ') + name)
    if not ok:
        sys.exit(1)
    passed += 1


def refused(fn, text):
    try:
        fn()
    except ValueError as e:
        return text in str(e)
    return False


def request():
    return json.loads((HERE / 'examples/requests/agents-python.json').read_text())


check('this A2C release generates for E2A v1.6.1 (e2a.bindings and its simulated profile)', E2A_REF == 'v1.6.1')
check('B-2 the default profile is "simulated"', g2c_v12.normalize({'agents': ['A']})['provider_profile'] == 'simulated')
check('a profile name that is not a name is refused', refused(
    lambda: g2c_v12.normalize({'agents': ['A'], 'provider_profile': '../etc/passwd'}), 'provider_profile'))

with tempfile.TemporaryDirectory() as tmp:
    report = build(request(), Path(tmp))
    root = Path(tmp) / 'agents-service'
    src = root / 'src' / 'agents_service'
    module = (src / 'services/bindings.py').read_text()
    check('the build succeeds', report['success'])
    check('B-1 the composition root is generated and binds from a profile',
          'bindings_from_profile(' in module and "DEFAULT_PROFILE = 'simulated'" in module
          and 'E2A_PROVIDER_PROFILE' in module)
    generated = '\n'.join(p.read_text() for p in src.rglob('*.py'))
    check('B-1 no generated source constructs a model service by name', 'SimulatedLLMService' not in generated)
    check('the generated tests bind the model from the simulated profile',
          'bindings_from_profile("simulated"' in (root / 'tests/test_workflow.py').read_text()
          and (root / 'tests/test_bindings.py').is_file())
    run = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests'], cwd=root,
                         capture_output=True, text=True, env={**__import__('os').environ, 'PYTHONPATH': str(root / 'src')})
    check('B-4 the generated tests pass: ' + ((run.stdout + run.stderr).strip().splitlines() or ['?'])[-1],
          run.returncode == 0)

    # B-5: one request through the generated workflow, with the config from the composition root
    sys.path.insert(0, str(root / 'src'))
    from e2a_simulated_llm import system_contains
    composition = importlib.import_module('agents_service.services.bindings')
    workflow = importlib.import_module('agents_service.workflow.order_workflow')
    llm = composition.bindings().llm_service
    llm.add_rule('router', system_contains('You are RouterAgent.'), '{"intent": "STATUS"}')
    llm.add_rule('status', system_contains('You are StatusAgent.'), '{"status": "PAID"}')
    state = workflow.OrderWorkflow().execute({'tenant_id': 't1', 'query': 'status of my order?'},
                                             composition.service_config(), idempotency_key='k-1')
    check('B-5 a request runs on the model bound from the profile',
          state['intent'] == 'STATUS' and [s['step'] for s in state['steps']] == ['route', 'act']
          and composition.bindings().profile.name == 'simulated')
    config = composition.service_config()
    check('B-5 the config carries the profile layer and the tools',
          'profile_settings' in config and config['llm_service'] is llm and 'tools' in config)

named = request()
named['a2c_sdlc'].update(provider_profile='anthropic_bedrock',
                         provider_requirement='e2a-managed-providers[anthropic-aws] @ git+https://example.invalid/p.git@v1')
with tempfile.TemporaryDirectory() as tmp:
    build(named, Path(tmp))
    root = Path(tmp) / 'agents-service'
    check('B-3 the request names the deployment profile',
          "DEFAULT_PROFILE = 'anthropic_bedrock'" in (root / 'src/agents_service/services/bindings.py').read_text())
    check('B-3 the provider package is a dependency of the generated project',
          'e2a-managed-providers' in (root / 'pyproject.toml').read_text())
    check('B-3 the tests still bind "simulated", so they need no provider account',
          'bindings_from_profile("simulated"' in (root / 'tests/test_workflow.py').read_text())

java = json.loads((HERE / 'examples/requests/java-azure-service.json').read_text())
java['a2c_sdlc']['provider_profile'] = 'simulated'
check('a profile on a Java service is refused, naming why',
      refused(lambda: build(java, Path(tempfile.mkdtemp())), 'needs a Python service'))

print(f'{passed} checks passed')
