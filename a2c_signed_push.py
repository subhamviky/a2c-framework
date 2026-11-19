"""Push a workflow's commit through GitHub's API so that GitHub signs it (A2C v1.5, AD-01).

A commit made with `git commit` inside a workflow is unsigned, and a repository that requires
signed commits refuses it. GitHub signs the commits it creates itself through its REST API for
the workflow's token. This recreates the local commit there, unchanged in content, author and
message (the trailers included), with the bot as committer, and points the branch at it.

    python -m a2c_signed_push --branch aidlc-change/svc/chg-1234abcd [--base <sha>]

It reads GITHUB_REPOSITORY, GITHUB_API_URL and GITHUB_TOKEN (the aidlc workflows set them).
The branch's commits since `--base` (default: the branch's merge base with origin/HEAD) are
recreated in order, so a run's single commit, or a few, keep their history.
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

Http = Callable[[str, str, Optional[Dict[str, Any]]], Tuple[int, Dict[str, Any]]]


class PushError(RuntimeError):
    pass


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise PushError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def github_http(api: str, token: str) -> Http:
    def call(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
        req = urllib.request.Request(api.rstrip('/') + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={'Authorization': f'Bearer {token}',
                                              'Accept': 'application/vnd.github+json',
                                              'X-GitHub-Api-Version': '2022-11-28',
                                              'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read() or b'{}')
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')
    return call


def _ok(status: int, answer: Dict[str, Any], what: str) -> Dict[str, Any]:
    if status not in (200, 201):
        raise PushError(f'{what}: GitHub answered {status}: {answer.get("message", answer)}')
    return answer


def recreate(repo: Path, owner_repo: str, branch: str, base: str, http: Http) -> List[str]:
    """Recreate base..branch on GitHub, one API commit per local commit. Returns the new SHAs."""
    commits = [c for c in _git(repo, 'rev-list', '--reverse', f'{base}..{branch}').split() if c]
    if not commits:
        raise PushError(f'nothing to push: {branch} has no commits after {base}')
    prefix = f'/repos/{owner_repo}/git'
    parent, created = base, []
    for sha in commits:
        entries = []
        for line in _git(repo, 'diff', '--no-renames', '--name-status', f'{sha}^', sha).splitlines():
            status, path = line.split('\t', 1)
            if status == 'D':
                entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': None})
                continue
            mode = _git(repo, 'ls-tree', sha, '--', path).split()[0]
            content = subprocess.run(['git', '-C', str(repo), 'show', f'{sha}:{path}'], capture_output=True).stdout
            blob = _ok(*http('POST', f'{prefix}/blobs', {'content': base64.b64encode(content).decode(),
                                                          'encoding': 'base64'}), f'blob {path}')
            entries.append({'path': path, 'mode': mode, 'type': 'blob', 'sha': blob['sha']})
        base_tree = _ok(*http('GET', f'{prefix}/commits/{parent}', None), 'parent commit')['tree']['sha']
        tree = _ok(*http('POST', f'{prefix}/trees', {'base_tree': base_tree, 'tree': entries}), 'tree')
        name, email, date = _git(repo, 'log', '-1', '--format=%an%x00%ae%x00%aI', sha).strip().split('\x00')
        message = _git(repo, 'log', '-1', '--format=%B', sha).rstrip('\n') + '\n'
        # no committer and no signature: GitHub commits as the token's bot and signs it
        commit = _ok(*http('POST', f'{prefix}/commits', {'message': message, 'tree': tree['sha'], 'parents': [parent],
                                                          'author': {'name': name, 'email': email, 'date': date}}),
                     'commit')
        parent = commit['sha']
        created.append(parent)
    status, _ = http('GET', f'{prefix}/ref/heads/{branch}', None)
    if status == 200:
        _ok(*http('PATCH', f'{prefix}/refs/heads/{branch}', {'sha': parent, 'force': False}), 'update branch')
    else:
        _ok(*http('POST', f'{prefix}/refs', {'ref': f'refs/heads/{branch}', 'sha': parent}), 'create branch')
    return created


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog='a2c_signed_push', description=__doc__.split('\n')[0])
    p.add_argument('--branch', required=True)
    p.add_argument('--base', help='the commit the run started from (default: merge base with origin/HEAD)')
    p.add_argument('--repo', default='.')
    args = p.parse_args(argv)
    owner_repo, token = os.environ.get('GITHUB_REPOSITORY'), os.environ.get('GITHUB_TOKEN')
    if not owner_repo or not token:
        print('GITHUB_REPOSITORY and GITHUB_TOKEN are needed', file=sys.stderr)
        return 1
    repo = Path(args.repo)
    base = args.base or _git(repo, 'merge-base', args.branch, 'origin/HEAD').strip()
    try:
        created = recreate(repo, owner_repo, args.branch, base,
                           github_http(os.environ.get('GITHUB_API_URL', 'https://api.github.com'), token))
    except PushError as e:
        print(f'::error::{e}', file=sys.stderr)
        return 1
    print(json.dumps({'branch': args.branch, 'commits': created}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
