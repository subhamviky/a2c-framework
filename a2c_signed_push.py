"""Push a workflow's commit so that GitHub signs it (A2C v1.5.4, AD-01) — opt-in.

GitHub signs a commit only when its own bot authors it: a commit created through the API with
another author is not signed (found on the first live run, v1.5.3). So a repository that requires
signed commits gets the model GitHub's Copilot agent uses: GitHub's GraphQL `createCommitOnBranch`
creates each commit, authored and signed by the workflow's bot, and the developer who started the
run is named in a `Co-authored-by` trailer (with every other trailer kept). Without the
requirement, the workflows use a plain `git push` instead: the developer is the author and the
bot the committer, unsigned, which is the default (AD-01 D1).

    python -m a2c_signed_push --branch aidlc-change/svc/chg-1234abcd --base <sha>

It reads GITHUB_REPOSITORY, GITHUB_API_URL and GITHUB_TOKEN (the aidlc workflows set them).
The branch's commits since `--base` are recreated in order.
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
    """Recreate base..branch on GitHub, signed by GitHub: one createCommitOnBranch per local commit,
    the developer kept as Co-authored-by. Returns the new SHAs."""
    commits = [c for c in _git(repo, 'rev-list', '--reverse', f'{base}..{branch}').split() if c]
    if not commits:
        raise PushError(f'nothing to push: {branch} has no commits after {base}')
    status, _ = http('GET', f'/repos/{owner_repo}/git/ref/heads/{branch}', None)
    if status == 200:
        raise PushError(f'branch {branch} already exists on GitHub')
    _ok(*http('POST', f'/repos/{owner_repo}/git/refs', {'ref': f'refs/heads/{branch}', 'sha': base}), 'create branch')
    head, created = base, []
    for sha in commits:
        additions, deletions = [], []
        for line in _git(repo, 'diff', '--no-renames', '--name-status', f'{sha}^', sha).splitlines():
            status_code, path = line.split('\t', 1)
            if status_code == 'D':
                deletions.append({'path': path})
            else:
                content = subprocess.run(['git', '-C', str(repo), 'show', f'{sha}:{path}'], capture_output=True).stdout
                additions.append({'path': path, 'contents': base64.b64encode(content).decode()})
        name, email = _git(repo, 'log', '-1', '--format=%an%x00%ae', sha).strip().split('\x00')
        headline = _git(repo, 'log', '-1', '--format=%s', sha).strip()
        body = _git(repo, 'log', '-1', '--format=%b', sha).rstrip('\n')
        body = f'{body}\nCo-authored-by: {name} <{email}>' if body else f'Co-authored-by: {name} <{email}>'
        query = ('mutation($input: CreateCommitOnBranchInput!) { createCommitOnBranch(input: $input) '
                 '{ commit { oid } } }')
        variables = {'input': {'branch': {'repositoryNameWithOwner': owner_repo, 'branchName': branch},
                               'message': {'headline': headline, 'body': body},
                               'fileChanges': {'additions': additions, 'deletions': deletions},
                               'expectedHeadOid': head}}
        answer = _ok(*http('POST', '/graphql', {'query': query, 'variables': variables}), 'commit')
        if answer.get('errors'):
            raise PushError(f"commit: {answer['errors'][0].get('message')}")
        head = answer['data']['createCommitOnBranch']['commit']['oid']
        created.append(head)
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
