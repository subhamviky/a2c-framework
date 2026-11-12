"""A2C v1.2 (wave C note C-02): declarations instead of patches. No network, no cloud.

A-3 settings · A-5 contracts to models · P-5 Maven coordinates · P-6 monorepo workflows ·
A-6 upgrade with a manifest."""
import json
import sys
import tempfile
from pathlib import Path

from a2c_contracts import Contract, ContractError, java, python, python_test
from a2c_layout import move_workflows, to_monorepo
from a2c_settings import SettingsError, normalize, python_module, terraform
from a2c_upgrade import upgrade, write_manifest
from base_project_bootstrapper import maven_dependency

passed = 0


def check(name, ok):
    global passed
    print(('PASS ' if ok else 'FAIL ') + name)
    if not ok:
        sys.exit(1)
    passed += 1


def refused(fn, error, text):
    try:
        fn()
    except error as e:
        return text in str(e)
    return False


# ------------------------------------------------------------------ A-3 settings
S = normalize([{'name': 'TABLE_NAME', 'default': 'recon'}, {'name': 'API_URL'}, {'name': 'TOKEN', 'secret': True}])
check('A-3 a lower-case name is refused', refused(lambda: normalize(['table']), SettingsError, 'UPPER_SNAKE_CASE'))
check('A-3 a secret with a default is refused',
      refused(lambda: normalize([{'name': 'T', 'secret': True, 'default': 'x'}]), SettingsError, 'secret store'))
check('A-3 a duplicate is refused', refused(lambda: normalize(['A', 'A']), SettingsError, 'twice'))
for cloud, secret_ref in (('aws', 'TOKEN_SECRET_ARN'), ('gcp', 'secret_key_ref'), ('azure', 'secret_name')):
    tf = terraform(cloud, S)
    check(f'A-3 {cloud}: variables, env and the secret reference',
          'variable "setting_api_url"' in tf['settings_variables'] and 'API_URL' in tf['settings_env']
          and secret_ref in tf['settings_env'] + tf['settings_resources'] and 'TOKEN' in tf['settings_test_asserts'])
check('A-3 a required setting has no default; Terraform holds no secret value',
      'default' not in tf['settings_variables'].split('setting_api_url')[1].split('}')[0]
      and 'secret_string' not in json.dumps(terraform('aws', S)))
ns = {}
exec(python_module(S), ns)
check('A-3 load_settings names the missing required settings',
      refused(lambda: ns['load_settings']({}), ns['MissingSettings'], 'API_URL, TOKEN'))
check('A-3 load_settings applies defaults', ns['load_settings']({'API_URL': 'u', 'TOKEN': 't'})['TABLE_NAME'] == 'recon')

# --------------------------------------------------------------- A-5 contracts
SCHEMA = {'type': 'object', 'required': ['id', 'kind', 'amount'], 'additionalProperties': False,
          'properties': {'id': {'type': 'string', 'format': 'uuid'}, 'kind': {'enum': ['A', 'B']},
                         'amount': {'type': 'string', 'format': 'decimal'},
                         'line': {'type': 'object', 'required': ['n'], 'properties': {'n': {'type': 'integer'}}}},
          'if': {'properties': {'kind': {'const': 'B'}}}, 'then': {'required': ['line']},
          'else': {'not': {'required': ['line']}},
          'examples': [{'id': '0b8f6c2e-1d2a-4c3b-9a8e-111111111111', 'kind': 'A', 'amount': '1.50'}]}
c = Contract('contracts/payment-event.v1.schema.json', SCHEMA)
ns = {}
exec(python(c), ns)
P = ns['PaymentEvent']
ok = SCHEMA['examples'][0]
check('A-5 the example parses; amount is a Decimal', str(P.model_validate(ok).amount) == '1.50')
check('A-5 an unknown field is refused (additionalProperties false)',
      refused(lambda: P.model_validate(dict(ok, x=1)), Exception, 'Extra inputs'))
check('A-5 "present only when" is enforced', refused(lambda: P.model_validate(dict(ok, kind='B')), Exception,
                                                    'line is present exactly when kind is B'))
check('A-5 an unsupported keyword is refused by name',
      refused(lambda: Contract('x.json', {'type': 'object', 'oneOf': []}), ContractError, '"oneOf"'))
check('A-5 Java records with Jackson names and enums',
      'record PaymentEvent(' in java(c, 'p')['PaymentEvent.java'] and '@JsonProperty("kind") Kind kind' in
      java(c, 'p')['PaymentEvent.java'] and 'java.math.BigDecimal amount' in java(c, 'p')['PaymentEvent.java'])
check('A-5 the generated test round-trips the examples', 'test_examples_round_trip' in python_test('pkg', [c]))

# -------------------------------------------------------- P-5 Maven coordinates
check('P-5 a starter short name stays a starter', 'spring-boot-starter-web' in maven_dependency('web'))
dep = maven_dependency('com.h2database:h2@runtime')
check('P-5 group:artifact@scope', '<groupId>com.h2database</groupId>' in dep and '<scope>runtime</scope>' in dep
      and '<version>' not in dep)
check('P-5 a version is kept', '<version>10.0.0</version>' in maven_dependency('org.flywaydb:flyway-core:10.0.0'))
check('P-5 a malformed coordinate is refused', refused(lambda: maven_dependency('a:b:c:d'), ValueError, 'group:artifact'))

# ------------------------------------------------------------ P-6 monorepo
CI = ('name: ci\n\non:\n  push:\n    branches: [main]\n  pull_request:\n\njobs:\n  test:\n    runs-on: ubuntu-latest\n'
      '    steps:\n      - uses: actions/setup-java@v5\n        with:\n          cache: maven\n'
      "      - if: hashFiles('pom.xml') != ''\n        run: mvn -B verify\n  iac:\n    runs-on: ubuntu-latest\n"
      '    defaults:\n      run:\n        working-directory: infra\n    steps:\n      - run: terraform test\n')
m = to_monorepo(CI, 'svc')
check('P-6 triggers are scoped to the service', m.count('paths: ["svc/**"') == 2)
check('P-6 jobs run in the service folder', 'working-directory: svc\n' in m and 'working-directory: svc/infra' in m)
check('P-6 file checks and the Maven cache point into it',
      "hashFiles('svc/pom.xml')" in m and 'cache-dependency-path: svc/pom.xml' in m)
with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / 'svc/.github/workflows').mkdir(parents=True)
    (Path(tmp) / 'svc/.github/workflows/ci.yml').write_text(CI)
    moved = move_workflows(Path(tmp), 'svc')
    check('P-6 workflows move to the repository root', moved == ['.github/workflows/svc-ci.yml']
          and not (Path(tmp) / 'svc/.github').exists())


# ------------------------------------------------------------- A-6 upgrade
def fake_build(version):
    def build(request, output):
        root = Path(output) / 'svc'
        (root / 'infra').mkdir(parents=True, exist_ok=True)
        (root / 'Dockerfile').write_text(f'FROM python:3.12 # {version}\n')
        (root / 'infra/main.tf').write_text('a = 1\nb = 2\n' if version == 'old' else 'a = 1\nb = 3\n')
        if version == 'new':
            (root / 'NEW.md').write_text('new file\n')
        return {'success': True}
    return build


REQ = {'context': {'project_name': 'svc'}}
with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    fake_build('old')(REQ, repo)
    write_manifest(repo, 'svc', REQ)
    (repo / 'svc/infra/main.tf').write_text('a = 9\nb = 2\n')          # your change
    (repo / 'svc/mine.py').write_text('x = 1\n')                       # your file
    report = upgrade(repo / 'svc', fake_build('new'))
    check('A-6 an untouched file is replaced', report['replaced'] == ['svc/Dockerfile']
          and 'new' in (repo / 'svc/Dockerfile').read_text())
    check('A-6 a new generated file is added', report['added'] == ['svc/NEW.md'])
    check('A-6 your changed file is kept and gets a patch', report['yours'] == ['svc/infra/main.tf']
          and (repo / 'svc/infra/main.tf').read_text() == 'a = 9\nb = 2\n'
          and '+b = 3' in (repo / 'a2c-upgrade.patch').read_text())
    check('A-6 a file that is not generated is never touched', (repo / 'svc/mine.py').read_text() == 'x = 1\n')
    check('A-6 the manifest now records the new generation',
          json.loads((repo / 'svc/.a2c/manifest.json').read_text())['files']['svc/NEW.md'])
    check('A-6 without a manifest or a baseline, the upgrade refuses',
          refused(lambda: upgrade(repo / 'other', fake_build('new')), Exception, '--baseline'))

print(f'{passed} checks passed')
