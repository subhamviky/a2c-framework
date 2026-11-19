"""A2C v1.5 (hub design note AD-01): aidlc-change on a generated E2A service. No network, no
cloud: the model's answers are recorded (replay), as they would be for any offline re-run.

Locate, plan, edit only what a developer could edit, verify, commit as the developer; refuse
framework-owned methods, declarations, infrastructure and records; commit nothing on failure."""
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import a2c_change as C
import a2c_cli

passed = 0
HERE = Path(__file__).resolve().parent
REQUEST = HERE / 'examples' / 'requests' / 'python-gcp-service.json'
AGENT = 'src/image_py_service/agents/image_agent.py'
NO_CI = {k: v for k, v in os.environ.items() if not k.startswith('GITHUB_')}
os.environ.clear()
os.environ.update(NO_CI)


def check(name, ok):
    global passed
    print(('PASS ' if ok else 'FAIL ') + name)
    if not ok:
        sys.exit(1)
    passed += 1


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def plan(subject='feat(image-agent): explain the degraded answer', targets=None, new_files=None, **extra):
    return {'summary': 'The degraded answer carries a reason.', 'kind': 'feature', 'subject': subject,
            'body': 'ImageAgent._fallback returns a reason with the degraded answer.',
            'changelog': 'The image agent\'s degraded answer now carries a reason.',
            'targets': targets if targets is not None else [{'file': AGENT, 'region': 'ImageAgent._fallback',
                                                             'why': 'the fallback answer'}],
            'new_files': new_files if new_files is not None else ['tests/test_fallback.py'],
            'declaration_changes': [], **extra}


def fallback(reason):
    return {'op': 'replace', 'file': AGENT, 'region': 'ImageAgent._fallback',
            'code': f"def _fallback(self, state, ctx):\n    \"\"\"The safe answer.\"\"\"\n"
                    f"    return {{'text': '', 'degraded': True, 'reason': '{reason}'}}"}


TEST = {'op': 'create', 'file': 'tests/test_fallback.py',
        'code': "from image_py_service.agents.image_agent import ImageAgent\n\n\n"
                "def test_fallback_gives_a_reason():\n"
                "    assert ImageAgent()._fallback({}, None)['reason'] == 'MODEL_OUTPUT_INVALID'\n"}


def run(repo, tmp, answers, *extra, prompt='Give the degraded answer a reason'):
    replay = Path(tmp) / f'replay-{abs(hash((prompt,) + extra))}.json'
    replay.write_text(json.dumps(answers))
    out, err = io.StringIO(), io.StringIO()
    cwd = os.getcwd()
    os.chdir(repo)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = C.main(['--project', 'image-py-service', '--prompt', prompt, '--llm', f'replay:{replay}',
                         '--yes', *extra])
    finally:
        os.chdir(cwd)
    text = out.getvalue()
    return rc, json.loads(text[text.index('\n{') + 1:] if not text.startswith('{') else text), err.getvalue()


with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp) / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    for key, value in (('user.name', 'Jane Developer'), ('user.email', 'jane@example.com'),
                       ('commit.gpgsign', 'false')):
        git(repo, 'config', key, value)
    git(repo, 'commit', '-q', '--allow-empty', '-m', 'init')
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        assert a2c_cli.main(['--request', str(REQUEST), '--output', str(repo), '--commit']) == 0
    scaffold = 'aidlc/image-py-service'
    project = repo / 'image-py-service'
    original_agent = (project / AGENT).read_text()

    # ---------------------------------------------------------------- the code index
    index = C.CodeIndex(project)
    regions = index.regions
    check('the index knows the agent\'s hooks', f'{AGENT}::ImageAgent._fallback' in regions)
    check('E2A\'s own data marks what the agent may never define',
          {'run', 'execute'} & index.class_owned(AGENT, 'ImageAgent'))
    check('the prompt ranks the agent\'s fallback among the first candidates',
          f'{AGENT}::ImageAgent._fallback' in [r.ref() for r in index.candidates('the agent fallback answer')[:5]])

    # ---------------------------------------------------------------- edit rules, before anything is written
    p = plan()
    check('an edit that defines a framework-owned method is refused',
          'framework-owned' in C.check_edit(C.Edit('add', AGENT, 'ImageAgent', 'def run(self, x):\n    return x'),
                                            {**p, 'targets': p['targets'] + [{'file': AGENT, 'region': 'ImageAgent'}]},
                                            index, False))
    check('an edit outside the plan is refused',
          'not in the plan' in C.check_edit(C.Edit('replace', AGENT, 'ImageAgent._handle_error', 'def _handle_error'
                                                   '(self, error, state, ctx):\n    pass'), p, index, False))
    check('the tool\'s records are never edited', 'never edited' in C.check_edit(
        C.Edit('create', '.a2c/changes/x.json', '', '{}'), {**p, 'new_files': ['.a2c/changes/x.json']}, index, False))
    check('versions and dependencies are not edits',
          'not an edit' in C.check_edit(C.Edit('replace', 'pyproject.toml', '', 'x'), p, index, False))
    check('Terraform needs --allow-infra', 'allow-infra' in C.check_plan(
        plan(targets=[{'file': 'infra/main.tf', 'region': '', 'why': ''}], new_files=[]), index, False)[0])
    check('with --allow-infra it may be planned',
          C.check_plan(plan(targets=[{'file': 'infra/main.tf', 'region': '', 'why': ''}], new_files=[]),
                       index, True) == [])

    # ---------------------------------------------------------------- a change, committed as the developer
    rc, rep, err = run(repo, tmp, [plan(), {'edits': [fallback('MODEL_OUTPUT_INVALID'), TEST]}], '--signoff')
    check('the change passes every check and is committed', rc == 0 and rep['success']
          and all(v == 'passed' for v in rep['checks'].values()))
    check('on its own branch, aidlc-change/<project>/<change-id>',
          rep['branch'] == f"aidlc-change/image-py-service/{rep['change_id']}"
          and git(repo, 'rev-parse', '--abbrev-ref', 'HEAD') == rep['branch'])
    log = git(repo, 'log', '-1', '--format=%an <%ae>|%cn|%B')
    check('authored and committed by the developer, with the plan\'s subject',
          log.startswith('Jane Developer <jane@example.com>|Jane Developer|feat(image-agent): explain the degraded'))
    check('Assisted-by names the tool and the model; the prompt is hashed; the sign-off is the developer\'s',
          ':replay' in log and 'Assisted-by: a2c-framework/' in log and 'Prompt-Sha256:' in log
          and 'Signed-off-by: Jane Developer <jane@example.com>' in log)
    files = git(repo, 'show', '--name-only', '--format=', 'HEAD').splitlines()
    check('the commit holds the change, its test, the changelog, the manifest and the change record',
          {f'image-py-service/{AGENT}', 'image-py-service/tests/test_fallback.py', 'image-py-service/CHANGELOG.md',
           'image-py-service/.a2c/manifest.json', rep['change_record']} <= set(files))
    check('the working tree is clean', git(repo, 'status', '--porcelain') == '')
    record = json.loads((repo / rep['change_record']).read_text())
    check('the change record: the prompt, the plan, before and after hashes, the checks',
          record['prompt'] == 'Give the degraded answer a reason' and record['kind'] == 'feature'
          and any(f['before'] is None for f in record['files']) and all(f['after'] for f in record['files'])
          and record['verification']['checks']['tests'] == 'passed')
    origins = json.loads((project / '.a2c/manifest.json').read_text())['origins']
    check('the manifest marks the changed files', origins[f'image-py-service/{AGENT}']['origin'] == 'changed')
    check('the changelog has the plan\'s line under Added',
          '### Added\n- The image agent\'s degraded answer now carries a reason.' in (project / 'CHANGELOG.md').read_text())
    check('the audit event says the developer started it and the agent did it',
          '"actor_is_agent": true' in err and '"outcome": "committed"' in err)
    git(repo, 'switch', '-q', scaffold)
    again_rc, again, _ = run(repo, tmp, [])
    check('the same change again reuses its branch instead of making another', again_rc == 0 and again.get('reused'))

    # ---------------------------------------------------------------- a failed check goes back to the model
    rc, rep, _ = run(repo, tmp, [plan(subject='fix(image-agent): reason code'),
                                 {'edits': [fallback('WRONG'), TEST]},
                                 {'edits': [fallback('MODEL_OUTPUT_INVALID'), TEST]}],
                     prompt='Use the reason code MODEL_OUTPUT_INVALID')
    check('a failing test goes back to the model, and the second attempt is committed',
          rc == 0 and rep['attempts'] == 2 and rep['checks']['tests'] == 'passed')
    git(repo, 'switch', '-q', scaffold)

    # ---------------------------------------------------------------- nothing committed when it cannot be verified
    head = git(repo, 'rev-parse', 'HEAD')
    rc, rep, err = run(repo, tmp, [plan(subject='feat(image-agent): broken'), {'edits': [fallback('WRONG'), TEST]}],
                       '--max-attempts', '1', prompt='Break it')
    check('verification failed: nothing committed, back on the starting branch, its branch removed',
          rc == 1 and not rep['success'] and git(repo, 'rev-parse', 'HEAD') == head
          and git(repo, 'rev-parse', '--abbrev-ref', 'HEAD') == scaffold
          and not git(repo, 'branch', '--list', f"aidlc-change/image-py-service/{rep['change_id']}"))
    check('the sources are restored', (project / AGENT).read_text() == original_agent
          and not (project / 'tests/test_fallback.py').exists())
    check('the last attempt is left as a patch with a report, for the developer',
          'WRONG' in (repo / 'aidlc-change.patch').read_text() and (repo / 'aidlc-change-report.json').is_file()
          and '"outcome": "failed verification"' in err)
    (repo / 'aidlc-change.patch').unlink()
    (repo / 'aidlc-change-report.json').unlink()

    # ---------------------------------------------------------------- refusals before any edit
    rc, rep, _ = run(repo, tmp, [plan(declaration_changes=['a new tool: credit_check'])], prompt='Add a tool')
    check('a declaration change is refused, with the way to declare it',
          rc == 1 and 'declaration change' in rep['error'] and 'aidlc-build --upgrade' in rep['error'])
    rc, rep, _ = run(repo, tmp, [plan(subject='feat: owned', targets=[{'file': AGENT, 'region': 'ImageAgent'}],
                                      new_files=[]),
                                 {'edits': [{'op': 'add', 'file': AGENT, 'region': 'ImageAgent',
                                             'code': 'def run(self, request):\n    return {}'}]}],
                     '--max-attempts', '1', prompt='Override run')
    check('an attempt to define a framework-owned method is refused and nothing is written',
          rc == 1 and 'framework-owned' in json.dumps(rep['attempts'])
          and (project / AGENT).read_text() == original_agent)
    for name in ('aidlc-change.patch', 'aidlc-change-report.json'):
        (repo / name).unlink()
    rc, rep, _ = run(repo, tmp, [], '--target', f'{AGENT}::ImageAgent.nothing', prompt='x')
    check('an unknown --target is refused before the model is asked', rc == 1 and 'not found' in rep['error'])
    (project / 'scratch.py').write_text('x = 1\n')
    rc, rep, _ = run(repo, tmp, [], prompt='dirty')
    check('a dirty working tree is refused', rc == 1 and 'uncommitted' in rep['error'])
    (project / 'scratch.py').unlink()

    args = C.parser().parse_args(['--project', str(project), '--prompt', 'Declined change',
                                  '--llm', f'replay:{Path(tmp) / "declined.json"}'])
    (Path(tmp) / 'declined.json').write_text(json.dumps([plan(subject='feat: declined')]))
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        result = C.change(args, out=lambda *_: None, ask=lambda _: 'n')
    check('the developer can decline the plan; nothing is written',
          result.get('declined') and git(repo, 'status', '--porcelain') == ''
          and git(repo, 'rev-parse', '--abbrev-ref', 'HEAD') == scaffold)

    # ---------------------------------------------------------------- the tests must be green before a change
    (project / 'tests/test_red.py').write_text('def test_red():\n    assert False\n')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', 'a failing test')
    rc, rep, _ = run(repo, tmp, [], prompt='on red')
    check('tests already failing on the base commit: refused, fix them first',
          rc == 1 and 'already fail' in rep['error'])

print(f'\n{passed} aidlc-change checks passed')
