"""A2C v1.2.1 (wave D note D-01): G2C generates Java on E2A v1.2, against e2a-java.

The generated project is compiled and tested with Maven when Maven is installed and e2a-java is in
the local Maven repository (CI installs it from E2A's tag first); otherwise that check is skipped,
and says so."""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import g2c_java12
from a2c_cli import E2A_REF, build

passed = 0
HERE = Path(__file__).resolve().parent
REQUEST = json.loads((HERE / 'examples/requests/agents-java.json').read_text())


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


check('e2a-java is pinned at the E2A version this A2C release generates for',
      'v' + g2c_java12.E2A_JAVA_VERSION == E2A_REF)
check('a stage e2a-java does not have is refused, naming the ones it has', refused(
    lambda: g2c_java12.normalize({'agents': ['A'], 'governance': {'stages': ['redaction']}}), 'available for Java'))

with tempfile.TemporaryDirectory() as tmp:
    report = build(copy.deepcopy(REQUEST), Path(tmp))
    root = Path(tmp) / 'agents-java-service'
    main = root / 'src/main/java/com/example/orders'
    check('the build succeeds with the critic at 1.0', report['success'] and report['critic_score'] == 1.0,
          json.dumps(report.get('findings')))
    check('three agents, the workflow, governance and tools are generated', all(
        (main / p).is_file() for p in ('agents/RouterAgent.java', 'agents/OrderAgent.java', 'agents/StatusAgent.java',
                                       'workflow/OrderWorkflow.java', 'governance/ServiceGovernance.java',
                                       'tools/SubmitPaymentTool.java')))
    check('no E2ABase.java: the project imports e2a-java (Case 2A for Java)',
          not list(root.rglob('E2ABase.java')) and 'com.subhamviky.e2a.agent.BaseAgent' in (main / 'agents/RouterAgent.java').read_text())
    order = (main / 'agents/OrderAgent.java').read_text()
    check('a deterministic agent has no model step; writes go through io_modify',
          'return null;' in order and 'io.call("submit_payment"' in order and 'evaluateOutput' not in order)
    check('the output schema is checked by evaluateOutput', 'List.of("ORDER", "STATUS").contains' in (main / 'agents/RouterAgent.java').read_text())
    check('a material tool is flagged', 'return true;' in (main / 'tools/SubmitPaymentTool.java').read_text())
    check('an AgentContract test per agent', len(list((root / 'src/test/java').rglob('*ContractTest.java'))) == 3)
    pom = (root / 'pom.xml').read_text()
    check('the pom depends on e2a-core and (test) e2a-test', '<artifactId>e2a-core</artifactId>' in pom
          and '<artifactId>e2a-test</artifactId>' in pom and f'<version>{g2c_java12.E2A_JAVA_VERSION}</version>' in pom)
    ci = (root / '.github/workflows/ci.yml').read_text()
    check('the CI installs e2a-java from E2A\'s tag before mvn verify',
          ci.index(f'--branch v{g2c_java12.E2A_JAVA_VERSION}') < ci.index('mvn -B verify'))
    check('the Dockerfile installs e2a-java before the build', 'e2a-framework.git /e2a' in (root / 'Dockerfile').read_text())
    jar = Path.home() / '.m2/repository/com/subhamviky/e2a/e2a-core' / g2c_java12.E2A_JAVA_VERSION
    if shutil.which('mvn') and jar.is_dir():
        done = subprocess.run(['mvn', '-B', '-q', 'verify'], cwd=root, capture_output=True, text=True)
        check('the generated project compiles and passes its tests (mvn verify, against e2a-java)',
              done.returncode == 0, (done.stdout + done.stderr)[-3000:])
    else:
        print('SKIP mvn verify of the generated project: Maven or e2a-java (local repository) not available')

legacy = json.loads((HERE / 'examples/requests/java-azure-service.json').read_text())
legacy['a2c_sdlc'].pop('contracts', None)
with tempfile.TemporaryDirectory() as tmp:
    report = build(legacy, Path(tmp))
    root = Path(tmp) / 'image-java-service'
    check('without e2a_contract a Java request stays on 1.1 (default unchanged), with no e2a-java',
          report['success'] and 'e2a-core' not in (root / 'pom.xml').read_text()
          and 'e2a-framework' not in (root / '.github/workflows/ci.yml').read_text())
    check('V13-01: the build report says the Java v1.1 skeleton is removed in A2C v1.3',
          any('removed in A2C v1.3' in w for w in report['warnings']))

print(f'\n{passed} checks passed')
