"""Repository layout (A2C v1.2, wave C design note C-02, item P-6).

GitHub runs only the workflows in the repository's root `.github/workflows/`. In a
repository that holds several services ("monorepo"), the per-service workflows that P0
and A2C generate inside the service folder never run. With
`context.repository_layout: "monorepo"` (or `aidlc-build --repository-layout monorepo`),
each generated workflow moves to the root as `<project>-<name>.yml`, scoped to the service:
its triggers carry `paths` filters, every job runs in the service folder, and file checks
(`hashFiles`) and step working directories point into it.
"""
import re
from pathlib import Path
from typing import List

LAYOUTS = ('single', 'monorepo')


def to_monorepo(text: str, project: str) -> str:
    paths = f'    paths: ["{project}/**", ".github/workflows/{project}-*.yml"]\n'
    text = re.sub(r'(?m)^name: (.+)$', lambda m: f'name: {project} {m.group(1)}', text, count=1)
    text = re.sub(r'(?m)^(  push:\n    branches: \[main\]\n)', lambda m: m.group(1) + paths, text)
    text = re.sub(r'(?m)^(  pull_request:\n)', lambda m: m.group(1) + paths, text)
    text = re.sub(r'(?m)^([ \t]+)cache: maven$', lambda m: f'{m.group(1)}cache: maven\n{m.group(1)}cache-dependency-path: {project}/pom.xml', text)
    text = re.sub(r"hashFiles\('([^']+)'\)", lambda m: f"hashFiles('{project}/{m.group(1)}')", text)
    text = re.sub(r'(?m)^([ \t]+working-directory: )(?!\$)(\S+)$', lambda m: f'{m.group(1)}{project}/{m.group(2)}', text)
    # every job without its own defaults runs in the service folder
    lines, out, i = text.split('\n'), [], 0
    in_jobs = False
    while i < len(lines):
        line = lines[i]
        out.append(line)
        if line.startswith('jobs:'):
            in_jobs = True
        elif in_jobs and re.match(r'^  [A-Za-z0-9_-]+:\s*$', line):
            block = []
            j = i + 1
            while j < len(lines) and (lines[j].startswith('    ') or not lines[j].strip()):
                block.append(lines[j])
                j += 1
            if not any(b.startswith('    defaults:') for b in block):
                for k, b in enumerate(block):
                    if b.startswith('    runs-on:'):
                        block[k + 1:k + 1] = ['    defaults:', '      run:', f'        working-directory: {project}']
                        break
            out.extend(block)
            i = j
            continue
        i += 1
    return '\n'.join(out)


def move_workflows(output: Path, project: str) -> List[str]:
    """Move <project>/.github/workflows/*.yml to <output>/.github/workflows/<project>-<name>.yml."""
    src = Path(output) / project / '.github' / 'workflows'
    if not src.is_dir():
        return []
    dest = Path(output) / '.github' / 'workflows'
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    for wf in sorted(src.glob('*.yml')):
        target = dest / f'{project}-{wf.name}'
        target.write_text(to_monorepo(wf.read_text(encoding='utf-8'), project), encoding='utf-8')
        wf.unlink()
        moved.append(str(target.relative_to(output)))
    for d in (src, src.parent):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return moved
