"""A2C v1.5.1 (hub design note AD-01, plan step 3): aidlc-change on a generated Java service
(Maven, e2a-java). Needs Maven, a JDK and e2a-java in the local Maven repository (CI installs it
from E2A's tag). The model's answers are recorded (replay); Maven really compiles and tests."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import a2c_change as C
import a2c_change_java as J
import a2c_cli

passed = 0
HERE = Path(__file__).resolve().parent
REQUEST = HERE / 'examples' / 'requests' / 'java-azure-service.json'
AGENT = 'src/main/java/com/example/image/agents/ImageAgent.java'
NEW_TEST = 'src/test/java/com/example/image/agents/ImageAgentFallbackTest.java'
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


if not (shutil.which('mvn') and shutil.which('javap')):
    print('SKIP Maven or a JDK is not installed')
    sys.exit(0)


def plan(subject='feat(image-agent): a clear degraded answer', **extra):
    return {'summary': 'The degraded answer names the reason.', 'kind': 'feature', 'subject': subject,
            'body': 'ImageAgent.fallback returns a reason code with the degraded answer.',
            'changelog': 'The image agent\'s degraded answer now names its reason.',
            'targets': [{'file': AGENT, 'region': 'ImageAgent.fallback', 'why': 'the degraded answer'}],
            'new_files': [NEW_TEST], 'declaration_changes': [], **extra}


def fallback(body):
    return {'op': 'replace', 'file': AGENT, 'region': 'ImageAgent.fallback',
            'code': '/** The degraded answer, with its reason. */\n@Override\n'
                    'protected Object fallback(Map<String, Object> state, RequestContext ctx) {\n'
                    f'    {body}\n}}'}


TEST = {'op': 'create', 'file': NEW_TEST, 'code': '''package com.example.image.agents;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;

class ImageAgentFallbackTest {
    @Test
    void theDegradedAnswerNamesItsReason() {
        Object answer = new ImageAgentProbe().degraded();
        assertEquals("MODEL_OUTPUT_INVALID", ((Map<?, ?>) answer).get("reason"));
    }

    static class ImageAgentProbe extends ImageAgent {
        Object degraded() {
            return fallback(new HashMap<>(), null);
        }
    }
}
'''}
GOOD = 'return Map.of("text", "", "degraded", true, "reason", "MODEL_OUTPUT_INVALID");'
BROKEN = 'return Map.of("text", "", "degraded", true, "reason", MODEL_OUTPUT_INVALID);'   # does not compile


def run(repo, tmp, answers, *extra, prompt='Name the reason of the degraded answer'):
    replay = Path(tmp) / f'replay-{abs(hash((prompt,) + extra))}.json'
    replay.write_text(json.dumps(answers))
    out, err = io.StringIO(), io.StringIO()
    cwd = os.getcwd()
    os.chdir(repo)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = C.main(['--project', 'image-java-service', '--prompt', prompt, '--llm', f'replay:{replay}',
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
    project = repo / 'image-java-service'
    git(repo, 'tag', 'v0.1.0')                      # released once: a feature now moves the version
    original = (project / AGENT).read_text()

    # ---------------------------------------------------------------- the Java reader
    sample = 'class A extends B {\n  /** doc { } */\n  @Override\n  protected Object f(String s) {\n' \
             '    return "}{";\n  }\n  // }\n  int x = 1;\n  public final void run() { }\n}\n'
    types = J.parse(sample)
    check('the Java reader finds members, with their Javadoc, past braces in comments and strings',
          [(m.name, m.start, m.end) for m in types[0].members] == [('f', 2, 6), ('run', 9, 9)]
          and types[0].extends == 'B')
    index = C.index_for(project)
    check('a Java project gets the Java index', isinstance(index, C.JavaIndex) and index.lang == 'java')
    check('the agent\'s hooks are regions', f'{AGENT}::ImageAgent.fallback' in index.regions)
    check('what e2a-java owns is read from its jar (javap): run() is final on BaseAgent',
          index.owned_source == 'javap' and 'run' in index.class_owned(AGENT, 'ImageAgent'))

    # ---------------------------------------------------------------- refusals before writing
    p = plan()
    check('a member that redefines run() is refused',
          'framework-owned' in C.check_edit(C.Edit('add', AGENT, 'ImageAgent',
                                                   'public Map<String, Object> run(Map<String, Object> s) {\n'
                                                   '    return s;\n}'),
                                            {**p, 'targets': p['targets'] + [{'file': AGENT, 'region': 'ImageAgent'}]},
                                            index, False))
    check('Java has no module-level region',
          'no module-level' in C.check_edit(C.Edit('add', AGENT, '<module>', 'int x;'),
                                            {**p, 'targets': [{'file': AGENT, 'region': '<module>'}]}, index, False))
    check('pom.xml is not an edit', 'not an edit' in C.check_edit(C.Edit('replace', 'pom.xml', '', 'x'), p,
                                                                   index, False))

    # ---------------------------------------------------------------- a change that first does not compile
    rc, rep, err = run(repo, tmp, [plan(), {'edits': [fallback(BROKEN), TEST]}, {'edits': [fallback(GOOD), TEST]}])
    check('the first attempt does not compile; Maven\'s error goes back to the model; the second is committed',
          rc == 0 and rep['attempts'] == 2 and rep['checks']['tests'] == 'passed')
    agent = (project / AGENT).read_text()
    check('only the member changed, with its Javadoc and annotation, in the class\'s indentation',
          '    /** The degraded answer, with its reason. */\n    @Override\n    protected Object fallback(' in agent
          and agent.count('protected Object fallback(') == 1 and 'evaluateOutput' in agent
          and agent.split('    /** The degraded answer')[0] == original.split('    @Override\n    protected Object fallback(')[0])
    log = git(repo, 'log', '-1', '--format=%an|%B')
    check('committed as the developer with the trailers', log.startswith('Jane Developer|feat(image-agent):')
          and 'Assisted-by: a2c-framework/' in log and 'Change-Id:' in log)
    check('a feature after release 0.1.0: the pom names 0.2.0-SNAPSHOT, not the parent\'s version',
          rep['version'] == {'file': 'pom.xml', 'from': '0.1.0-SNAPSHOT', 'to': '0.2.0-SNAPSHOT'}
          and '<version>0.2.0-SNAPSHOT</version>' in (project / 'pom.xml').read_text())
    check('the changelog, the record and the new test are in the commit',
          {f'image-java-service/{NEW_TEST}', 'image-java-service/CHANGELOG.md', 'image-java-service/pom.xml',
           rep['change_record']} <= set(git(repo, 'show', '--name-only', '--format=', 'HEAD').splitlines()))
    check('Maven\'s target/ is not committed and the tree is clean',
          git(repo, 'status', '--porcelain') == ''
          and not any('/target/' in f for f in git(repo, 'show', '--name-only', '--format=', 'HEAD').splitlines()))

print(f'\n{passed} aidlc-change Java checks passed')
