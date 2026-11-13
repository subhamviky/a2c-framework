"""A2C v1.2.1 (wave C note C-04): E2A's release gate in generated projects, evaluation sets
declared in the request, and Phase C on E2A's checks."""
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from a2c_cli import ProjectStaticPipeline, build
from a2c_evaluation import normalize_evaluation

passed = 0
HERE = Path(__file__).resolve().parent
BASE = json.loads((HERE / 'examples/requests/agents-python.json').read_text())


def check(name, ok, detail=''):
    global passed
    print(('PASS ' if ok else 'FAIL ') + name + (f'\n{detail}' if not ok and detail else ''))
    if not ok:
        sys.exit(1)
    passed += 1


def refused(fn, text):
    try:
        fn()
    except ValueError as e:
        return text in str(e)
    return False


def gate(root, module, *extra):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(root / 'src')] + sys.path))
    return subprocess.run([sys.executable, '-m', module, '--skip-tests', '--report', str(root / 'gate.json'), *extra],
                          cwd=root, env=env, capture_output=True, text=True)


check('an unknown evaluation key is refused', refused(lambda: normalize_evaluation({'sets': 'x.json'}), 'unknown keys'))
check('a path outside the project is refused', refused(lambda: normalize_evaluation({'set': '../x.json'}), 'relative path'))
check('a threshold outside (0, 1] is refused', refused(lambda: normalize_evaluation({'threshold': 1.5}), 'threshold'))
check('no evaluation declared means none', normalize_evaluation(None) is None and normalize_evaluation({}) is None)

java = json.loads((HERE / 'examples/requests/java-azure-service.json').read_text())
java.setdefault('a2c_sdlc', {})['evaluation'] = {'set': 'evals/golden.json'}
with tempfile.TemporaryDirectory() as tmp:
    check('evaluation on a Java service is refused (no E2A v1.2 for Java)',
          refused(lambda: build(java, Path(tmp)), 'needs a Python service on E2A v1.2'))

request = copy.deepcopy(BASE)
request['a2c_sdlc']['evaluation'] = {'set': 'evals/golden.json', 'redteam': 'evals/redteam.json', 'threshold': 0.8}
with tempfile.TemporaryDirectory() as tmp:
    report = build(request, Path(tmp))
    root = Path(tmp) / 'agents-service'
    pkg = root / 'src' / 'agents_service'
    check('the build succeeds', report['success'], json.dumps(report.get('findings')))
    check('the gate and the evaluation files are generated',
          (pkg / 'release' / 'gate.py').is_file() and (root / 'evals/golden.json').is_file()
          and (root / 'evals/redteam.json').is_file())
    ci = (root / '.github/workflows/ci.yml').read_text()
    check('the CI runs the generated gate after the tests, with the declared threshold',
          ci.index('pytest -q') < ci.index('python -m agents_service.release.gate --skip-tests')
          and '"faithfulness_threshold": 0.8' in ci)
    check('Phase C read the evaluation sets (one example case each)',
          report['evaluation_cases'] == {'evals/golden.json': 1, 'evals/redteam.json': 2}
          and 'well formed' in report['stage_notes']['ragas_gate'])
    check('Phase C used E2A conformance (strict) on the generated code',
          'e2a.conformance (strict)' in report['stage_notes']['scaffold_compliance'])
    done = gate(root, 'agents_service.release.gate')
    check('the generated gate fails until the scorer is written',
          done.returncode == 1 and 'implement _score_case' in done.stdout, done.stdout + done.stderr)
    text = (pkg / 'release' / 'gate.py').read_text()
    text = text.replace('raise NotImplementedError("decide how a case is scored: implement _score_case(case)")',
                        "return 1.0 if case.get('expected') else 0.0")
    text = text.replace('raise NotImplementedError("decide how a red-team case is checked: implement _probe(case)")',
                        'return []')
    (pkg / 'release' / 'gate.py').write_text(text)
    done = gate(root, 'agents_service.release.gate')
    result = json.loads((root / 'gate.json').read_text())
    check('with a scorer and a probe written, the generated gate passes all seven stages',
          done.returncode == 0 and result['rag_eval_score'] == 1.0 and len(result['stages']) == 7,
          done.stdout + done.stderr)

    (pkg / 'settings_local.py').write_text('TOKEN = "AKIA' + 'ABCDEFGHIJKLMNOP"\n')
    phase_c = ProjectStaticPipeline(root, 'python', 'gcp', e2a_contract='1.2',
                                    evaluation=request['a2c_sdlc']['evaluation'])
    check('Phase C fails a project with a planted secret',
          phase_c.run_pipeline({})['status'] == 'FAILED' and any('aws access key' in f for f in phase_c.findings))
    (pkg / 'settings_local.py').unlink()
    agent = pkg / 'agents' / 'order_agent.py'
    agent.write_text(agent.read_text() + '\n    def run(self, state, config=None, **kwargs):\n        return state\n')
    phase_c = ProjectStaticPipeline(root, 'python', 'gcp', e2a_contract='1.2')
    check('Phase C fails a project with an R1 override',
          phase_c.run_pipeline({})['status'] == 'FAILED' and any('R1' in f for f in phase_c.findings),
          json.dumps(phase_c.findings))

with tempfile.TemporaryDirectory() as tmp:
    report = build(copy.deepcopy(BASE), Path(tmp))
    root = Path(tmp) / 'agents-service'
    ci = (root / '.github/workflows/ci.yml').read_text()
    check('without an evaluation, an E2A v1.2 service runs the generic gate in its CI',
          report['success'] and 'python -m e2a.release --skip-tests' in ci
          and not (root / 'src/agents_service/release').exists())
    done = gate(root, 'e2a.release')
    result = json.loads((root / 'gate.json').read_text())
    check('the generic gate passes on the generated code, the domain stages NOT_CONFIGURED',
          done.returncode == 0 and result['stages']['ragas_gate'].startswith('NOT_CONFIGURED'),
          done.stdout + done.stderr)

print(f'\n{passed} checks passed')
