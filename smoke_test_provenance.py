"""A2C v1.5 (hub design note AD-01): provenance for every AI-DLC run. No network, no cloud.

The developer is the author; the tool is disclosed (Assisted-by), never signs off on its own;
change records, manifest origins, versions, the changelog and the audit event."""
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import a2c_cli
import a2c_provenance as P
from a2c_upgrade import upgrade, write_manifest

passed = 0
HERE = Path(__file__).resolve().parent
REQUEST = HERE / 'examples' / 'requests' / 'python-gcp-service.json'


def check(name, ok):
    global passed
    print(('PASS ' if ok else 'FAIL ') + name)
    if not ok:
        sys.exit(1)
    passed += 1


def refused(fn, text, error=P.ProvenanceError):
    try:
        fn()
    except error as e:
        return text in str(e)
    return False


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def new_repo(path, identity=True):
    path.mkdir(parents=True, exist_ok=True)
    git(path, 'init', '-q', '-b', 'main')
    git(path, 'config', 'commit.gpgsign', 'false')
    if identity:
        git(path, 'config', 'user.name', 'Jane Developer')
        git(path, 'config', 'user.email', 'jane@example.com')
    else:                                   # an empty identity, whatever the global configuration says
        git(path, 'config', 'user.name', '')
        git(path, 'config', 'user.email', '')
    subprocess.run(['git', '-C', str(path), '-c', 'user.name=init', '-c', 'user.email=init@example.com',
                    'commit', '-q', '--allow-empty', '-m', 'init'], check=True, capture_output=True)
    return path


def cli(argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    saved = dict(os.environ)
    os.environ.update(env or {})
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = a2c_cli.main(argv)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return rc, json.loads(out.getvalue()), err.getvalue()


NO_CI = {k: v for k, v in os.environ.items() if not k.startswith('GITHUB_')}
GH = {'GITHUB_ACTIONS': 'true', 'GITHUB_TRIGGERING_ACTOR': 'jdev', 'AIDLC_DEVELOPER_ID': '4242',
      'GITHUB_REPOSITORY': 'acme/landscape', 'GITHUB_RUN_ID': '77', 'GITHUB_SERVER_URL': 'https://github.com'}

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    # ---------------------------------------------------------------- who the developer is
    repo = new_repo(tmp / 'r1')
    dev = P.resolve_developer(P.Git(repo), env=NO_CI)
    check('the developer is the checkout\'s git identity', dev.ident() == 'Jane Developer <jane@example.com>'
          and dev.source == 'git-config')
    check('--author may only rename the same identity',
          P.resolve_developer(P.Git(repo), 'J. Developer <jane@example.com>', env=NO_CI).name == 'J. Developer')
    check('--author cannot attribute the run to someone else',
          refused(lambda: P.resolve_developer(P.Git(repo), 'Bob <bob@example.com>', env=NO_CI), 'someone else'))
    anon = new_repo(tmp / 'anon', identity=False)
    check('no git identity: the run is refused', refused(lambda: P.resolve_developer(P.Git(anon), env=NO_CI),
                                                         'no developer'))
    wf = P.resolve_developer(P.Git(repo), env=GH)
    check('in a workflow the developer is the person who started the run, with their no-reply address',
          wf.ident() == 'jdev <4242+jdev@users.noreply.github.com>' and wf.source == 'github-triggering-actor')
    check('in a workflow the bot is the committer, the developer the author',
          P.committer_for(wf) == (P.BOT_NAME, P.BOT_EMAIL) and P.committer_for(dev) is None)
    check('a workflow started by a bot is refused',
          refused(lambda: P.resolve_developer(P.Git(repo), env={**GH, 'GITHUB_TRIGGERING_ACTOR': 'renovate[bot]'}),
                  'is a bot'))
    check('a workflow that does not say who started it is refused',
          refused(lambda: P.resolve_developer(P.Git(repo), env={**GH, 'AIDLC_DEVELOPER_ID': ''}), 'did not say'))
    check('--author is refused in a workflow',
          refused(lambda: P.resolve_developer(P.Git(repo), 'x <x@y.z>', env=GH), 'not accepted'))

    # ---------------------------------------------------------------- the commit message
    policy = P.load_policy(tmp)
    msg = P.commit_message('feat(x): do it', 'Why.', change='chg-1', model='m-1', developer=dev, policy=policy,
                           prompt='do it', env=NO_CI)
    check('trailers: Change-Id, Assisted-by in the kernel format, the prompt hash',
          'Change-Id: chg-1' in msg and f'Assisted-by: a2c-framework/{P.a2c_version()}:m-1' in msg
          and f"Prompt-Sha256: {P.sha256('do it')}" in msg)
    check('no Signed-off-by unless the developer asks for it', 'Signed-off-by' not in msg)
    check('--signoff adds the developer\'s own sign-off',
          'Signed-off-by: Jane Developer <jane@example.com>' in P.commit_message(
              's', '', change='c', model='m', developer=dev, policy=policy, signoff=True, env=NO_CI))
    check('the workflow run is linked (AIDLC-Run)',
          'AIDLC-Run: https://github.com/acme/landscape/actions/runs/77' in P.commit_message(
              's', '', change='c', model='m', developer=wf, policy=policy, env=GH))
    check('Co-authored-by for the tool is off by default', 'Co-authored-by' not in msg)
    (tmp / 'pol' / '.a2c').mkdir(parents=True)
    (tmp / 'pol' / '.a2c' / 'policy.json').write_text(json.dumps(
        {'prompt_storage': 'hash', 'attribution': {'co_author': True, 'co_author_identity': 'A2C <a2c@example.com>'}}))
    pol = P.load_policy(tmp / 'pol')
    check('a project can list the tool as co-author',
          'Co-authored-by: A2C <a2c@example.com>' in P.commit_message('s', '', change='c', model='m', developer=dev,
                                                                       policy=pol, env=NO_CI))
    (tmp / 'bad' / '.a2c').mkdir(parents=True)
    (tmp / 'bad' / '.a2c' / 'policy.json').write_text(json.dumps({'attribution': {'co_author': True}}))
    check('co-author without an identity is refused', refused(lambda: P.load_policy(tmp / 'bad'), 'co_author_identity'))

    # ---------------------------------------------------------------- the change record and redaction
    secret = 'use key AKIAABCDEFGHIJKLMNOP please'
    check('secrets are redacted from the prompt', 'AKIA' not in P.redact(secret) and 'REDACTED' in P.redact(secret))
    rec = P.ChangeRecord(id='chg-x', kind='feature', developer={'name': 'J'}, base_commit='abc', tooling={})
    path = P.write_change_record(tmp / 'rec', rec, secret, policy)
    data = json.loads(path.read_text())
    check('the change record keeps the redacted prompt and its hash',
          'AKIA' not in data['prompt'] and data['prompt_sha256'] == P.sha256(secret))
    rec2 = P.ChangeRecord(id='chg-y', kind='feature', developer={'name': 'J'}, base_commit='abc', tooling={})
    data2 = json.loads(P.write_change_record(tmp / 'rec', rec2, secret, pol).read_text())
    check('prompt_storage "hash" keeps only the hash', data2['prompt'] is None and data2['prompt_sha256'])

    # ---------------------------------------------------------------- versions and the changelog
    check('a project never released keeps its version', P.next_version('0.1.0', None, 'feature') == '0.1.0')
    check('a feature after release 1.2.0 is 1.3.0', P.next_version('1.2.0', '1.2.0', 'feature') == '1.3.0')
    check('a fix after a feature (same release) does not bump again', P.next_version('1.3.0', '1.2.0', 'fix') == '1.3.0')
    check('a breaking change after a feature is the next major', P.next_version('1.3.0', '1.2.0', 'breaking') == '2.0.0')
    check('before 1.0 a breaking change is a minor', P.next_version('0.3.0', '0.3.0', 'breaking') == '0.4.0')
    proj = tmp / 'v'
    proj.mkdir()
    (proj / 'pyproject.toml').write_text('[tool.poetry]\nname = "v"\nversion = "1.2.0"\n\n[tool.x]\nversion = "9"\n')
    out = P.bump_version(proj, 'feature', '1.2.0')
    check('pyproject.toml: the project version moves, nothing else',
          out == {'file': 'pyproject.toml', 'from': '1.2.0', 'to': '1.3.0'}
          and 'version = "1.3.0"' in (proj / 'pyproject.toml').read_text()
          and 'version = "9"' in (proj / 'pyproject.toml').read_text())
    jp = tmp / 'j'
    jp.mkdir()
    (jp / 'pom.xml').write_text('<project><parent><version>3.3.0</version></parent><artifactId>j</artifactId>'
                                '<version>0.4.1</version><dependencies><dependency><version>1</version>'
                                '</dependency></dependencies></project>')
    P.bump_version(jp, 'fix', '0.4.1')
    pom = (jp / 'pom.xml').read_text()
    check('pom.xml: the project version moves, not the parent\'s or a dependency\'s',
          '<version>0.4.2</version>' in pom and '<version>3.3.0</version>' in pom and '<version>1</version>' in pom)
    P.add_changelog_entry(proj, 'feature', 'First thing.')
    P.add_changelog_entry(proj, 'fix', 'A fix.')
    P.add_changelog_entry(proj, 'feature', 'Second thing.')
    log = (proj / 'CHANGELOG.md').read_text()
    check('changelog: Keep a Changelog sections under [Unreleased]',
          log.count('### Added') == 1 and log.count('### Fixed') == 1 and '- Second thing.' in log
          and log.index('## [Unreleased]') < log.index('### Added'))
    check('no AI marker in a changelog line', 'AI' not in log.split('## [Unreleased]')[1])

    # ---------------------------------------------------------------- aidlc-build --commit
    repo = new_repo(tmp / 'build')
    rc, rep, err = cli(['--request', str(REQUEST), '--output', str(repo), '--commit', '--signoff'], NO_CI)
    prov = rep.get('provenance', {})
    log = git(repo, 'log', '-1', '--format=%an <%ae>|%cn|%B')
    check('aidlc-build --commit commits on aidlc/<project>', rc == 0 and prov.get('branch') == 'aidlc/image-py-service'
          and git(repo, 'rev-parse', '--abbrev-ref', 'HEAD') == 'aidlc/image-py-service')
    check('the developer is author and committer of a local run',
          log.startswith('Jane Developer <jane@example.com>|Jane Developer|feat(image-py-service)'))
    check('the creation commit discloses the tool and carries the developer\'s sign-off',
          'Assisted-by: a2c-framework/' in log and ':template' in log and 'Signed-off-by: Jane Developer' in log)
    check('nothing is left uncommitted', git(repo, 'status', '--porcelain') == '')
    rec = json.loads((repo / prov['change_record']).read_text())
    check('the change record names the developer, the base commit and the checks',
          rec['kind'] == 'create' and rec['developer']['email'] == 'jane@example.com'
          and rec['base_commit'] and rec['verification']['phase_reached'] == 'E2A_VERIFIED')
    manifest = json.loads((repo / 'image-py-service/.a2c/manifest.json').read_text())
    check('the manifest records every generated file\'s origin',
          manifest['origins'] and all(o['origin'] == 'generated' for o in manifest['origins'].values()))
    check('an audit event is emitted', 'AIDLC-AUDIT' in err and '"actor_is_agent": true' in err
          and '"initiated_by": "Jane Developer <jane@example.com>"' in err)
    rc2, rep2, _ = cli(['--request', str(REQUEST), '--output', str(repo), '--commit'], NO_CI)
    check('a second creation of the same project is refused', rc2 == 1 and 'already exists' in rep2['errors'][0])
    (repo / 'scratch.txt').write_text('x')
    rc3, rep3, _ = cli(['--request', str(REQUEST), '--output', str(repo / 'other'), '--commit'], NO_CI)
    check('a dirty working tree is refused before anything is generated',
          rc3 == 1 and 'uncommitted' in rep3['errors'][0] and not (repo / 'other').exists())
    (repo / 'scratch.txt').unlink()
    anon_repo = new_repo(tmp / 'anon-build', identity=False)
    rc4, rep4, _ = cli(['--request', str(REQUEST), '--output', str(anon_repo), '--commit'], NO_CI)
    check('no developer: refused, nothing generated', rc4 == 1 and 'no developer' in rep4['errors'][0]
          and not (anon_repo / 'image-py-service').exists())

    # ---------------------------------------------------------------- in a workflow
    wrepo = new_repo(tmp / 'wf')
    rc5, rep5, _ = cli(['--request', str(REQUEST), '--output', str(wrepo), '--commit'], GH)
    wlog = git(wrepo, 'log', '-1', '--format=%an <%ae>|%cn <%ce>|%B')
    check('workflow: the person who started it is the author, the bot the committer',
          rc5 == 0 and wlog.startswith('jdev <4242+jdev@users.noreply.github.com>|github-actions[bot] '))
    check('workflow: the run is linked and nobody signs off on the developer\'s behalf',
          'AIDLC-Run: https://github.com/acme/landscape/actions/runs/77' in wlog and 'Signed-off-by' not in wlog)

    # ---------------------------------------------------------------- --upgrade --commit
    rc6, rep6, _ = cli(['--upgrade', str(repo / 'image-py-service'), '--commit'], NO_CI)
    check('--upgrade --commit on an up-to-date project commits only its record',
          rc6 == 0 and rep6['provenance']['branch'].startswith('aidlc-upgrade/image-py-service/'))
    ulog = git(repo, 'log', '-1', '--format=%an|%s|%B')
    check('the upgrade commit is the developer\'s, with the trailers',
          ulog.startswith('Jane Developer|chore(image-py-service): upgrade the scaffold') and 'Assisted-by:' in ulog)

    # ---------------------------------------------------------------- upgrade keeps aidlc-change's files
    def fake_build(version):
        def build(request, output):
            root = Path(output) / 'svc'
            root.mkdir(parents=True, exist_ok=True)
            (root / 'agent.py').write_text(f'x = "{version}"\n')
            return {'success': True}
        return build
    req = {'context': {'project_name': 'svc'}}
    up = tmp / 'up'
    up.mkdir()
    fake_build('old')(req, up)
    write_manifest(up, 'svc', req)
    P.mark_origins(up / 'svc', ['svc/agent.py'], 'changed', 'chg-1')
    report = upgrade(up / 'svc', fake_build('new'))
    check('a file aidlc-change changed is never replaced by --upgrade, even if its text is the generated one',
          report['yours'] == ['svc/agent.py'] and (up / 'svc/agent.py').read_text() == 'x = "old"\n')
    check('the origins survive the upgrade',
          json.loads((up / 'svc/.a2c/manifest.json').read_text())['origins']['svc/agent.py']['origin'] == 'changed')

    # ---------------------------------------------------------------- workflow commits signed by GitHub
    import a2c_signed_push as SP
    calls = []

    def fake_github(method, path, body):
        calls.append((method, path, body))
        if path.endswith('/blobs'):
            return 201, {'sha': f'blob{len(calls)}'}
        if '/git/commits/' in path:
            return 200, {'tree': {'sha': 'basetree'}}
        if path.endswith('/trees'):
            return 201, {'sha': 'tree1'}
        if path.endswith('/commits'):
            return 201, {'sha': 'signed1'}
        if '/ref/heads/' in path:
            return 404, {}
        return 201, {}
    base = git(wrepo, 'rev-parse', 'HEAD~1')
    created = SP.recreate(wrepo, 'acme/landscape', 'aidlc/image-py-service', base, fake_github)
    commit_body = next(b for m, p, b in calls if p.endswith('/git/commits'))
    check('signed push: the commit is recreated through the API with the developer as author, no committer',
          created == ['signed1'] and commit_body['author']['email'] == '4242+jdev@users.noreply.github.com'
          and 'committer' not in commit_body and 'signature' not in commit_body)
    check('signed push: the message keeps every trailer, and the branch is created',
          'Assisted-by: a2c-framework/' in commit_body['message'] and 'AIDLC-Run:' in commit_body['message']
          and calls[-1][1].endswith('/git/refs') and calls[-1][2]['sha'] == 'signed1')
    check('signed push: every file of the commit is sent as a blob',
          sum(1 for m, p, b in calls if p.endswith('/blobs')) == len(
              git(wrepo, 'diff', '--name-only', base, 'HEAD').splitlines()))

print(f'\n{passed} provenance checks passed')
