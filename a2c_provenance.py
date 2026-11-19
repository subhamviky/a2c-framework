"""Provenance for every AI-DLC run (A2C v1.5, hub design note AD-01).

Whether a run creates a project (`aidlc-build --commit`), upgrades it (`--upgrade --commit`)
or changes existing code (`aidlc-change`), it ends the same way a developer's own work does:
a commit on a branch, authored by the developer, for a reviewed pull request.

  Developer         who asked: the checkout's git identity, or in a GitHub workflow the
                    person who started the run. A run with no identifiable developer is refused.
  commit message    the repository's convention, then the trailers:
                      Change-Id:      links the commit to its change record
                      Assisted-by:    a2c-framework/<version>:<model>  (the Linux kernel's and
                                      Fedora's disclosure format; only on commits whose content
                                      the tool produced)
                      AIDLC-Run:      the workflow run, when there is one
                      Prompt-Sha256:  the exact prompt, when there is one
                      Co-authored-by: the tool, only if the project's policy asks for it
                      Signed-off-by:  ONLY when the developer passes --signoff; never added by
                                      the tool on its own (only a person can certify the DCO)
  change record     .a2c/changes/<change-id>.json: what git cannot hold (the prompt, redacted
                    for secrets; the plan; tool and model; file hashes; the checks)
  manifest origin   .a2c/manifest.json gains `origins`: generated / changed, and the change id
  audit event       one JSON line per run on the `a2c.audit` logger (and stderr), with the
                    fields of GitHub's agentic audit log: actor, actor_is_agent, initiated_by...
  version           the next release's version, from the kind of change (semantic versioning);
                    tags stay manual
  changelog         a Keep-a-Changelog entry under [Unreleased]

The project's own policy lives in `.a2c/policy.json` (written by people, never by the tool):
    {"prompt_storage": "text" | "hash",
     "attribution": {"co_author": false, "co_author_identity": "Name <email>"}}
"""
import datetime as _dt
import hashlib
import json
import logging
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from e2a.release import SECRET_PATTERNS

__all__ = ['ProvenanceError', 'Developer', 'Git', 'resolve_developer', 'a2c_version', 'change_id',
           'load_policy', 'redact', 'commit_message', 'ChangeRecord', 'write_change_record',
           'audit_event', 'emit_audit', 'bump_version', 'next_version', 'add_changelog_entry',
           'mark_origins', 'run_url', 'latest_release', 'committer_for', 'file_hash', 'sha256', 'KINDS', 'BOT_NAME', 'BOT_EMAIL']

KINDS = ('create', 'upgrade', 'feature', 'fix', 'refactor', 'breaking')
BUMP = {'breaking': 'major', 'feature': 'minor', 'fix': 'patch', 'refactor': 'patch', 'upgrade': 'patch'}
CHANGELOG_SECTION = {'feature': 'Added', 'fix': 'Fixed', 'refactor': 'Changed', 'upgrade': 'Changed',
                     'breaking': 'Changed'}
BOT_NAME = 'github-actions[bot]'
BOT_EMAIL = '41898282+github-actions[bot]@users.noreply.github.com'
POLICY = Path('.a2c') / 'policy.json'
CHANGES = Path('.a2c') / 'changes'
MANIFEST = Path('.a2c') / 'manifest.json'
_SEMVER = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)$')

audit_log = logging.getLogger('a2c.audit')


class ProvenanceError(RuntimeError):
    """The run cannot be recorded truthfully (no developer, dirty tree, branch exists...)."""


def a2c_version() -> str:
    try:
        return metadata.version('a2c-framework')
    except metadata.PackageNotFoundError:          # running from a checkout
        return 'unknown'


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


# ------------------------------------------------------------------ git
class Git:
    """The few git operations a run needs, on one repository (subprocess, no library)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def run(self, *args: str, env: Optional[Dict[str, str]] = None, check: bool = True) -> str:
        proc = subprocess.run(['git', '-C', str(self.path), *args], capture_output=True, text=True,
                              env={**os.environ, **(env or {})})
        if check and proc.returncode != 0:
            raise ProvenanceError(f"git {' '.join(args)}: {(proc.stderr or proc.stdout).strip()}")
        return proc.stdout.strip()

    def root(self) -> Path:
        return Path(self.run('rev-parse', '--show-toplevel'))

    def config(self, key: str) -> str:
        return self.run('config', '--get', key, check=False)

    def head(self) -> str:
        return self.run('rev-parse', 'HEAD')

    def current_branch(self) -> str:
        return self.run('rev-parse', '--abbrev-ref', 'HEAD')

    def is_clean(self) -> bool:
        return self.run('status', '--porcelain') == ''

    def branch_exists(self, name: str) -> bool:
        return self.run('rev-parse', '--verify', '--quiet', f'refs/heads/{name}', check=False) != ''

    def switch_new(self, name: str) -> None:
        self.run('switch', '-q', '-c', name)

    def switch(self, name: str) -> None:
        self.run('switch', '-q', name)

    def delete_branch(self, name: str) -> None:
        self.run('branch', '-q', '-D', name, check=False)

    def add(self, paths: Iterable[str]) -> None:
        paths = [p for p in paths if p]
        if paths:
            self.run('add', '-A', '--', *paths)

    def staged(self) -> List[str]:
        return [p for p in self.run('diff', '--cached', '--name-only').splitlines() if p]

    def latest_release_tag(self) -> Optional[str]:
        tags = self.run('tag', '--merged', 'HEAD', '--sort=-v:refname', check=False).splitlines()
        return next((t for t in tags if _SEMVER.match(t.strip())), None)

    def commit(self, message: str, author: 'Developer', committer: Optional[Tuple[str, str]] = None) -> str:
        env = {'GIT_AUTHOR_NAME': author.name, 'GIT_AUTHOR_EMAIL': author.email}
        if committer:
            env.update({'GIT_COMMITTER_NAME': committer[0], 'GIT_COMMITTER_EMAIL': committer[1]})
        # the developer's own git configuration decides signing (commit.gpgsign); nothing is forced
        proc = subprocess.run(['git', '-C', str(self.path), 'commit', '-q', '-F', '-'], input=message,
                              capture_output=True, text=True, env={**os.environ, **env})
        if proc.returncode != 0:
            raise ProvenanceError(f'git commit: {(proc.stderr or proc.stdout).strip()}')
        return self.head()


# ------------------------------------------------------------------ the developer
@dataclass(frozen=True)
class Developer:
    name: str
    email: str
    source: str                 # git-config | github-triggering-actor

    def ident(self) -> str:
        return f'{self.name} <{self.email}>'


_IDENT = re.compile(r'^\s*(?P<name>[^<>]+?)\s*<(?P<email>[^<>@\s]+@[^<>\s]+)>\s*$')


def in_github_actions(env: Optional[Dict[str, str]] = None) -> bool:
    return (env if env is not None else os.environ).get('GITHUB_ACTIONS') == 'true'


def resolve_developer(git: Git, author: Optional[str] = None,
                      env: Optional[Dict[str, str]] = None) -> Developer:
    """Who asked for this run. Refuses (ProvenanceError) when nobody can be identified."""
    env = dict(os.environ if env is None else env)
    if in_github_actions(env):
        if author:
            raise ProvenanceError('--author is not accepted in a workflow: the author is the person '
                                  'who started the run')
        login = env.get('AIDLC_DEVELOPER_LOGIN') or env.get('GITHUB_TRIGGERING_ACTOR') or env.get('GITHUB_ACTOR')
        uid = env.get('AIDLC_DEVELOPER_ID', '')
        if not login or not uid.isdigit():
            raise ProvenanceError('the workflow did not say who started it: set AIDLC_DEVELOPER_LOGIN and '
                                  'AIDLC_DEVELOPER_ID (the aidlc workflows do)')
        if login.endswith('[bot]'):
            raise ProvenanceError(f'{login} is a bot, not a developer: an AI-DLC run must be started by a person')
        return Developer(login, f'{uid}+{login}@users.noreply.github.com', 'github-triggering-actor')
    name, email = git.config('user.name'), git.config('user.email')
    if not name or not email:
        raise ProvenanceError('no developer: set `git config user.name` and `git config user.email` in this '
                              'checkout; an AI-DLC run is always authored by the person who started it')
    if author:
        match = _IDENT.match(author)
        if not match:
            raise ProvenanceError(f'--author must be "Name <email>", not {author!r}')
        if match['email'].lower() != email.lower():
            raise ProvenanceError(f"--author {match['email']} is not this checkout's git identity ({email}): "
                                  'a run cannot be attributed to someone else')
        name = match['name']
    return Developer(name, email, 'git-config')


def committer_for(developer: Developer) -> Optional[Tuple[str, str]]:
    """In a workflow the bot really writes the commit: it is the committer, the developer the author."""
    return (BOT_NAME, BOT_EMAIL) if developer.source == 'github-triggering-actor' else None


def run_url(env: Optional[Dict[str, str]] = None) -> Optional[str]:
    env = os.environ if env is None else env
    if env.get('GITHUB_RUN_ID') and env.get('GITHUB_REPOSITORY'):
        server = env.get('GITHUB_SERVER_URL', 'https://github.com')
        return f"{server}/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"
    return None


# ------------------------------------------------------------------ policy, ids, redaction
def load_policy(project_dir: Path) -> Dict[str, Any]:
    path = Path(project_dir) / POLICY
    policy = {'prompt_storage': 'text', 'attribution': {'co_author': False, 'co_author_identity': ''}}
    if path.is_file():
        given = json.loads(path.read_text(encoding='utf-8'))
        policy['prompt_storage'] = given.get('prompt_storage', 'text')
        policy['attribution'].update(given.get('attribution') or {})
    if policy['prompt_storage'] not in ('text', 'hash'):
        raise ProvenanceError(f"{POLICY}: prompt_storage must be 'text' or 'hash'")
    if policy['attribution'].get('co_author') and not _IDENT.match(policy['attribution'].get('co_author_identity', '')):
        raise ProvenanceError(f'{POLICY}: attribution.co_author needs co_author_identity "Name <email>"')
    return policy


def change_id(*parts: str) -> str:
    return 'chg-' + hashlib.sha256('\x1f'.join(parts).encode()).hexdigest()[:8]


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def redact(text: str) -> str:
    """Anything that looks like a secret (E2A's release-gate patterns) is replaced."""
    for name, pattern in SECRET_PATTERNS:
        text = pattern.sub(f'[REDACTED {name}]', text)
    return text


def file_hash(path: Path) -> Optional[str]:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


# ------------------------------------------------------------------ the commit message
def commit_message(subject: str, body: str, *, change: str, model: str, developer: Developer,
                   policy: Dict[str, Any], prompt: Optional[str] = None, signoff: bool = False,
                   env: Optional[Dict[str, str]] = None) -> str:
    subject = ' '.join(subject.split())[:100]
    trailers = [f'Change-Id: {change}', f'Assisted-by: a2c-framework/{a2c_version()}:{model}']
    url = run_url(env)
    if url:
        trailers.append(f'AIDLC-Run: {url}')
    if prompt:
        trailers.append(f'Prompt-Sha256: {sha256(prompt)}')
    attribution = policy.get('attribution', {})
    if attribution.get('co_author'):
        trailers.append(f"Co-authored-by: {attribution['co_author_identity']}")
    if signoff:                                  # the developer asked for it; the tool never adds it alone
        trailers.append(f'Signed-off-by: {developer.ident()}')
    parts = [subject]
    if body.strip():
        parts.append(body.strip())
    return '\n\n'.join(parts) + '\n\n' + '\n'.join(trailers) + '\n'


# ------------------------------------------------------------------ the change record
@dataclass
class ChangeRecord:
    id: str
    kind: str
    developer: Dict[str, str]
    base_commit: str
    tooling: Dict[str, Any]
    prompt: Optional[str] = None
    prompt_sha256: Optional[str] = None
    plan: Dict[str, Any] = field(default_factory=dict)
    files: List[Dict[str, Optional[str]]] = field(default_factory=list)
    verification: Dict[str, Any] = field(default_factory=dict)
    run: Optional[str] = None
    created_at: str = field(default_factory=_now)


def write_change_record(project_dir: Path, record: ChangeRecord, prompt: Optional[str],
                        policy: Dict[str, Any]) -> Path:
    if record.kind not in KINDS:
        raise ProvenanceError(f'unknown kind {record.kind!r}: {KINDS}')
    if prompt:
        record.prompt_sha256 = sha256(prompt)
        record.prompt = redact(prompt) if policy.get('prompt_storage') == 'text' else None
    path = Path(project_dir) / CHANGES / f'{record.id}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(record), indent=2, sort_keys=True, default=str) + '\n', encoding='utf-8')
    return path


# ------------------------------------------------------------------ the audit event
def audit_event(*, change: str, kind: str, developer: Developer, model: str, outcome: str,
                files_changed: int, project: str, env: Optional[Dict[str, str]] = None,
                **extra: Any) -> Dict[str, Any]:
    """The fields of GitHub's agentic audit log, for one AI-DLC run."""
    return {'event': 'aidlc.run', 'time': _now(), 'actor': f'a2c-framework/{a2c_version()}',
            'actor_is_agent': True, 'initiated_by': developer.ident(), 'initiated_via': developer.source,
            'change_id': change, 'kind': kind, 'project': project, 'model': model, 'outcome': outcome,
            'files_changed': files_changed, 'run_url': run_url(env), **extra}


def emit_audit(event: Dict[str, Any], stream: Optional[Callable[[str], None]] = None) -> None:
    line = json.dumps(event, sort_keys=True, default=str)
    audit_log.info(line)                         # an OpenTelemetry logging handler can export this
    if stream is not None:
        stream(f'AIDLC-AUDIT {line}')


# ------------------------------------------------------------------ versions and the changelog
def _parse(version: str) -> Tuple[int, int, int]:
    match = _SEMVER.match(version.strip())
    if not match:
        raise ProvenanceError(f'not a semantic version: {version!r}')
    return int(match[1]), int(match[2]), int(match[3])


def _bump(version: Tuple[int, int, int], level: str) -> Tuple[int, int, int]:
    major, minor, patch = version
    if level == 'major':
        return (major + 1, 0, 0) if major > 0 else (0, minor + 1, 0)   # 0.x: a breaking change is a minor
    if level == 'minor':
        return major, minor + 1, 0
    return major, minor, patch + 1


def next_version(current: str, released: Optional[str], kind: str) -> str:
    """The version of the next release. The file's version names the next release, so several
    changes between two releases do not bump twice: it only moves when it is below what this change
    needs from the last release. A project never released keeps its version until its first release."""
    level = BUMP.get(kind)
    if not level or not released:
        return current
    needed = _bump(_parse(released), level)
    return '.'.join(map(str, max(_parse(current), needed)))


def latest_release(git: 'Git', project_dir: Path) -> Optional[str]:
    """The last released version: the newest semantic-version tag, else the newest release
    heading of CHANGELOG.md (`## [1.2.0]`)."""
    tag = git.latest_release_tag()
    if tag:
        return tag.lstrip('v')
    changelog = Path(project_dir) / 'CHANGELOG.md'
    if changelog.is_file():
        match = re.search(r'(?m)^## \[(\d+\.\d+\.\d+)\]', changelog.read_text(encoding='utf-8'))
        if match:
            return match[1]
    return None


_PY_VERSION = re.compile(r'(?ms)^\[(?:project|tool\.poetry)\]\s*\n(?:(?!^\[).)*?^version\s*=\s*"([^"]+)"')


def _version_file(project_dir: Path) -> Tuple[Optional[Path], Optional[str]]:
    pyproject, pom = Path(project_dir) / 'pyproject.toml', Path(project_dir) / 'pom.xml'
    if pyproject.is_file():
        match = _PY_VERSION.search(pyproject.read_text(encoding='utf-8'))
        return (pyproject, match[1]) if match else (None, None)
    if pom.is_file():
        text = re.sub(r'(?s)<parent>.*?</parent>', '', pom.read_text(encoding='utf-8'))
        head = re.split(r'<(?:dependencies|build|properties|dependencyManagement)>', text)[0]
        match = re.search(r'<version>([^<]+)</version>', head)
        return (pom, match[1]) if match else (None, None)
    return None, None


def bump_version(project_dir: Path, kind: str, released: Optional[str]) -> Optional[Dict[str, str]]:
    """Move the project's version for this change; returns {file, from, to} or None. A suffix such as
    Maven's -SNAPSHOT is kept: 0.1.0-SNAPSHOT names the next release 0.1.0."""
    path, current = _version_file(project_dir)
    match = re.match(r'^(\d+\.\d+\.\d+)(-[0-9A-Za-z.-]+)?$', current or '')
    if path is None or not match:
        return None
    core, suffix = match.group(1), match.group(2) or ''
    new = next_version(core, released.lstrip('v') if released else None, kind) + suffix
    if new == current:
        return {'file': path.name, 'from': current, 'to': current}
    text = path.read_text(encoding='utf-8')
    if path.suffix == '.toml':
        found = _PY_VERSION.search(text)
        text = text[:found.start(1)] + new + text[found.end(1):]
    else:
        stripped = re.sub(r'(?s)<parent>.*?</parent>', lambda m: ' ' * len(m.group(0)), text)
        found = re.search(r'<version>([^<]+)</version>', stripped)
        text = text[:found.start(1)] + new + text[found.end(1):]
    path.write_text(text, encoding='utf-8')
    return {'file': path.name, 'from': current, 'to': new}


CHANGELOG_HEAD = ('# Changelog\n\nAll notable changes to this project are documented in this file. The format '
                  'follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses '
                  '[semantic versioning](https://semver.org/).\n\n## [Unreleased]\n')


def add_changelog_entry(project_dir: Path, kind: str, line: str) -> Optional[Path]:
    section = CHANGELOG_SECTION.get(kind)
    if not section or not line.strip():
        return None
    path = Path(project_dir) / 'CHANGELOG.md'
    text = path.read_text(encoding='utf-8') if path.is_file() else CHANGELOG_HEAD
    if '## [Unreleased]' not in text:
        first = re.search(r'(?m)^## ', text)
        at = first.start() if first else len(text)
        text = text[:at].rstrip('\n') + '\n\n## [Unreleased]\n\n' + text[at:]
    entry = ('**Breaking:** ' if kind == 'breaking' else '') + ' '.join(line.split())
    start = text.index('## [Unreleased]') + len('## [Unreleased]')
    nxt = re.search(r'(?m)^## ', text[start:])
    end = start + nxt.start() if nxt else len(text)
    block = text[start:end]
    heading = f'### {section}'
    if heading in block:
        at = block.index(heading) + len(heading)
        block = block[:at] + f'\n- {entry}' + block[at:]
    else:
        block = block.rstrip('\n') + f'\n\n{heading}\n- {entry}\n\n'
    text = text[:start] + block + text[end:].lstrip('\n')
    path.write_text(text.rstrip('\n') + '\n', encoding='utf-8')
    return path


# ------------------------------------------------------------------ the manifest's origins
def mark_origins(project_dir: Path, rel_paths: Iterable[str], origin: str, change: str) -> bool:
    """Record in .a2c/manifest.json which files a run produced (generated) or changed (changed).
    Paths are relative to the repository root, as the manifest's `files` are."""
    path = Path(project_dir) / MANIFEST
    if not path.is_file():
        return False
    manifest = json.loads(path.read_text(encoding='utf-8'))
    origins = manifest.setdefault('origins', {})
    for rel in rel_paths:
        origins[rel] = {'origin': origin, 'change_id': change}
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return True


# ------------------------------------------------------------------ one run, start to commit
@dataclass
class Run:
    """The start of a recorded run: who, where, from which commit, on which branch."""
    git: Git
    developer: Developer
    repo_root: Path
    project_dir: Path
    base_commit: str
    start_branch: str
    branch: str
    change: str
    kind: str
    policy: Dict[str, Any]

    def rel(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.repo_root).as_posix()


def start_run(project_dir: Path, *, kind: str, change_parts: Iterable[str], branch: str,
              author: Optional[str] = None, env: Optional[Dict[str, str]] = None,
              reuse_branch: bool = False) -> Run:
    """Check everything that would make the record untrue BEFORE anything is written: a developer,
    a git repository, a clean tree (as a developer would stash first), a new branch."""
    project_dir = Path(project_dir).resolve()
    probe = project_dir
    while not probe.is_dir() and probe != probe.parent:      # a new project: its nearest existing folder
        probe = probe.parent
    git = Git(probe)
    try:
        repo_root = git.root()
    except ProvenanceError as e:
        raise ProvenanceError(f'{probe} is not in a git repository: a recorded run commits its work') from e
    git = Git(repo_root)
    developer = resolve_developer(git, author, env)
    if not git.is_clean():
        raise ProvenanceError('the working tree has uncommitted changes: commit or stash them first, so the '
                              'run starts from a known commit')
    base = git.head()
    change = change_id(*change_parts, base)
    branch = branch.replace('{change}', change)
    if git.branch_exists(branch) and not reuse_branch:
        raise ProvenanceError(f'branch {branch} already exists')
    policy = load_policy(project_dir) if project_dir.is_dir() else load_policy(Path('/nonexistent'))
    return Run(git, developer, repo_root, project_dir, base, git.current_branch(), branch, change, kind, policy)


def finish_run(run: Run, *, subject: str, body: str, model: str, files: Iterable[str],
               before: Optional[Dict[str, Optional[str]]] = None, prompt: Optional[str] = None,
               plan: Optional[Dict[str, Any]] = None, verification: Optional[Dict[str, Any]] = None,
               changelog_line: str = '', origin: str = 'generated', extra_paths: Iterable[str] = (),
               signoff: bool = False, env: Optional[Dict[str, str]] = None,
               stream: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Version, changelog, origins, change record, commit and audit event, in that order.
    `files` are paths relative to the repository root that the run produced or changed."""
    files = sorted(dict.fromkeys(files))
    before = dict(before or {})
    version = None
    if run.kind in BUMP:
        version = bump_version(run.project_dir, run.kind, latest_release(run.git, run.project_dir))
    changelog = add_changelog_entry(run.project_dir, run.kind, changelog_line)
    mark_origins(run.project_dir, files, origin, run.change)
    record = ChangeRecord(
        id=run.change, kind=run.kind, developer=asdict(run.developer), base_commit=run.base_commit,
        tooling={'a2c_framework': a2c_version(), 'model': model}, plan=dict(plan or {}),
        files=[{'path': f, 'before': before.get(f), 'after': file_hash(run.repo_root / f)} for f in files],
        verification=dict(verification or {}), run=run_url(env))
    if version:
        record.plan['version'] = version
    record_path = write_change_record(run.project_dir, record, prompt, run.policy)
    paths = list(files) + list(extra_paths) + [run.rel(record_path)]
    for extra in (changelog, run.project_dir / MANIFEST,
                  (run.project_dir / version['file']) if version else None):
        if extra is not None and Path(extra).exists():
            paths.append(run.rel(Path(extra)))
    run.git.add(paths)
    message = commit_message(subject, body, change=run.change, model=model, developer=run.developer,
                             policy=run.policy, prompt=prompt, signoff=signoff, env=env)
    sha = run.git.commit(message, run.developer, committer_for(run.developer))
    event = audit_event(change=run.change, kind=run.kind, developer=run.developer, model=model,
                        outcome='committed', files_changed=len(files), project=run.project_dir.name,
                        env=env, commit=sha, branch=run.branch)
    emit_audit(event, stream)
    return {'change_id': run.change, 'branch': run.branch, 'commit': sha, 'version': version,
            'change_record': run.rel(record_path), 'audit': event}


def abandon_run(run: Run, *, model: str, outcome: str, reason: str, env: Optional[Dict[str, str]] = None,
                stream: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Nothing is committed: back to the starting branch, the run's branch removed, the event logged."""
    if run.git.current_branch() == run.branch:
        run.git.switch(run.start_branch)
        run.git.delete_branch(run.branch)
    event = audit_event(change=run.change, kind=run.kind, developer=run.developer, model=model, outcome=outcome,
                        files_changed=0, project=run.project_dir.name, env=env, reason=reason[:500])
    emit_audit(event, stream)
    return event
