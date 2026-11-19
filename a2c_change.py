"""aidlc-change: change existing code from a prompt or a command (A2C v1.5, hub design note AD-01).

    aidlc-change --project services/o2c-agent-service \\
        --prompt "Refuse orders above the customer's credit limit, with reason CREDIT_LIMIT" \\
        [--target src/pkg/agents/order_agent.py::OrderAgent._evaluate_output] [--kind feature] \\
        [--llm profile:<name> | replay:<answers.json>] [--yes] [--signoff] [--pr] [--allow-infra]

  0. Identify  the developer (a2c_provenance); refuse if unknown; clean tree; the base commit
  1. Locate    index the project's Python code: classes, methods, which methods E2A owns
               (from E2A's own conformance data); rank them against the prompt
  2. Plan      the model proposes targets, kind, subject, changelog line; a declaration change
               (a new agent, tool, contract, setting, dependency) is refused here: declare it in
               the request and regenerate (C-02), then change the logic. The developer confirms
  3. Edit      the model answers with structured edits, only inside the plan and only where a
               developer could edit by hand: never a framework-owned method, never .a2c/, never
               pyproject/pom, Terraform/CI/Dockerfiles only with --allow-infra
  4. Verify    compile, E2A conformance (no new findings), secret scan, the A2C critic's
               concurrency checks, the project's tests; failures go back to the model (3 tries)
  5. Record    version, changelog, manifest origins, change record, audit event
  6. Commit    on aidlc-change/<project>/<change-id>, authored by the developer; --pr opens the pull request

If verification still fails, nothing is committed: the files are restored, and the last attempt
is left as aidlc-change.patch with aidlc-change-report.json for the developer.

The model is bound through E2A: `profile:<name>` (e2a.bindings, any provider profile) or
`replay:<file>` (recorded answers, for tests and for re-running a reviewed session offline).
`--record <file>` saves a live session's answers for replay. Python projects since v1.5.0;
Java projects (Maven, e2a-java) since v1.5.1: members of a class are the regions, the methods
e2a-java declares `final` are owned, and Maven compiles and tests the change.
"""
import argparse
import ast
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import a2c_change_java as J
from a2c_concurrency import run_coro_sync
from a2c_provenance import (KINDS, ProvenanceError, abandon_run, file_hash, finish_run, redact, sha256,
                            start_run)
from e2a.release import SECRET_PATTERNS

__all__ = ['ChangeError', 'Region', 'CodeIndex', 'Edit', 'apply_edits', 'check_edit', 'main', 'change',
           'replay_llm', 'MAX_ATTEMPTS']

MAX_ATTEMPTS = 3
SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', 'target', '.terraform', '__pycache__', '.a2c',
             '.pytest_cache', 'build', 'dist', '.aidlc'}
INFRA = re.compile(r'(^|/)(infra/|\.github/|Dockerfile[^/]*$|docker-compose[^/]*$|[^/]+\.tf$|[^/]+\.tfvars$)')
FORBIDDEN = re.compile(r'(^|/)(\.a2c/|\.env[^/]*$|\.git/)')
DECLARATIONS = re.compile(r'(^|/)(pyproject\.toml|pom\.xml|poetry\.lock|requirements[^/]*\.txt|CHANGELOG\.md)$')
CHANGE_KINDS = [k for k in KINDS if k not in ('create', 'upgrade')]

PLAN_SYSTEM = """You are the A2C change planner for an E2A service. You receive a developer's change request, \
the candidate code regions of the project, and the rules. Answer with ONE JSON object and nothing else:
{"summary": str, "kind": "feature"|"fix"|"refactor"|"breaking", "subject": str (a conventional-commit \
subject, e.g. "feat(order-agent): refuse orders above the credit limit"), "body": str (what changes and why, \
for the commit message), "changelog": str (one line for CHANGELOG.md, written for its readers), \
"targets": [{"file": str, "region": str, "why": str}], "new_files": [str], "declaration_changes": [str]}.
Rules: a region is "Class.method", "function", "Class" (to add a method to it) or "<module>" (to append to \
a Python file). In Java a region is "Type.method" or "Type" (nested types: "Outer.Inner.method"). Never target a method marked framework-owned. List in declaration_changes anything that needs a \
new agent, tool, contract, setting or dependency: those are declared in the request, not edited."""

EDIT_SYSTEM = """You are the A2C change implementer for an E2A service. Implement the approved plan. Answer \
with ONE JSON object and nothing else: {"edits": [{"op": "replace"|"add"|"create", "file": str, \
"region": str, "code": str}]}.
- replace: "code" is the complete new definition of the region ("Class.method" or "function"), with its \
decorators and docstring.
- add: "code" is one or more new methods (region "Class") or new top-level code (region "<module>").
- create: a new file from the plan's new_files; "code" is the whole file.
- In Java, "code" is the whole member: its Javadoc, annotations (@Override), signature and body; an \
added method goes inside the type. Java has no "<module>" region.
Write only inside the plan. Never define or override a framework-owned method. Keep the project's style; add \
or update tests for the behaviour you change."""


class ChangeError(RuntimeError):
    """The change cannot be made as asked (refused before anything is written)."""


# ------------------------------------------------------------------ 1. the code index
@dataclass
class Region:
    file: str                 # relative to the project
    name: str                 # Class.method | function | Class
    kind: str                 # method | function | class
    lineno: int
    end_lineno: int
    owned: bool = False       # framework-owned: never edited
    doc: str = ''
    bases: List[str] = field(default_factory=list)

    def ref(self) -> str:
        return f'{self.file}::{self.name}'


def _framework_owned() -> Dict[str, Set[str]]:
    """E2A class name -> methods a subclass must not define (E2A's own conformance data)."""
    from e2a import conformance
    return {name: set(fc.owned) | set(fc.private) for name, fc in conformance._framework_classes().items()}


class CodeIndex:
    lang = 'python'

    def __init__(self, project: Path) -> None:
        self.project = Path(project)
        self.regions: Dict[str, Region] = {}
        self.files: List[str] = []
        self._owned = _framework_owned()
        self._build()

    def _py_files(self):
        for path in sorted(self.project.rglob('*.py')):
            rel = path.relative_to(self.project)
            if not (SKIP_DIRS & set(rel.parts)):
                yield path, rel.as_posix()

    def _build(self) -> None:
        from e2a import conformance
        classes: Dict[str, Tuple[str, ast.ClassDef, Dict[str, str]]] = {}
        for path, rel in self._py_files():
            self.files.append(rel)
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except SyntaxError:
                continue
            aliases = conformance._framework_aliases(tree, self._owned)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self._add(Region(rel, node.name, 'function', _first(node), node.end_lineno,
                                     doc=(ast.get_docstring(node) or '').split('\n')[0]))
                elif isinstance(node, ast.ClassDef):
                    classes[node.name] = (rel, node, aliases)
        for cname, (rel, node, aliases) in classes.items():
            owned = self._owned_for(cname, classes)
            bases = [conformance._base_name(b) for b in node.bases]
            self._add(Region(rel, cname, 'class', _first(node), node.end_lineno,
                             doc=(ast.get_docstring(node) or '').split('\n')[0], bases=bases))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self._add(Region(rel, f'{cname}.{item.name}', 'method', _first(item), item.end_lineno,
                                     owned=item.name in owned,
                                     doc=(ast.get_docstring(item) or '').split('\n')[0]))

    def _owned_for(self, cname: str, classes, seen=None) -> Set[str]:
        """Methods owned by any E2A class this class inherits from, through project classes too."""
        seen = seen or set()
        if cname in seen or cname not in classes:
            return set()
        seen.add(cname)
        from e2a import conformance
        rel, node, aliases = classes[cname]
        owned: Set[str] = set()
        for base in node.bases:
            name = conformance._base_name(base)
            if name in aliases and aliases[name] in self._owned:
                owned |= self._owned[aliases[name]]
            owned |= self._owned_for(name, classes, seen)
        return owned

    def _add(self, region: Region) -> None:
        self.regions[region.ref()] = region

    def owned_methods(self, file: str, cls: str) -> Set[str]:
        return {r.name.split('.', 1)[1] for r in self.regions.values()
                if r.file == file and r.kind == 'method' and r.name.startswith(cls + '.') and r.owned}

    def class_owned(self, file: str, cls: str) -> Set[str]:
        """Every framework-owned name for a class (including the ones it does not define)."""
        classes = {}
        for path, rel in self._py_files():
            if rel != file:
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'))
            from e2a import conformance
            aliases = conformance._framework_aliases(tree, self._owned)
            classes = {n.name: (rel, n, aliases) for n in tree.body if isinstance(n, ast.ClassDef)}
        return self._owned_for(cls, classes)

    def candidates(self, prompt: str, limit: int = 25) -> List[Region]:
        words = {w for w in re.findall(r'[a-z0-9]+', _split_camel(prompt).lower()) if len(w) > 2}
        scored = []
        for region in self.regions.values():
            if region.owned:
                continue
            text = _split_camel(f'{region.file} {region.name} {region.doc}').lower()
            tokens = set(re.findall(r'[a-z0-9]+', text))
            score = len(words & tokens) + (0.5 if region.kind != 'function' and '/agents/' in region.file else 0)
            if '/tests/' in f'/{region.file}' or region.file.startswith('tests/'):
                score -= 0.25
            scored.append((score, region.ref(), region))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [r for _, _, r in scored[:limit]]


class JavaIndex(CodeIndex):
    """The same index for a Maven project on e2a-java (a2c_change_java)."""
    lang = 'java'

    def __init__(self, project: Path) -> None:
        self.project = Path(project)
        self.regions, self.files = {}, []
        owned = J.e2a_java_owned(self.project)
        self.owned_source = 'javap' if owned is not None else 'fallback'
        self._owned = owned or {}
        self._types: Dict[str, Tuple[str, Any]] = {}
        self._build()

    def _build(self) -> None:
        for path in sorted(self.project.rglob('*.java')):
            rel = path.relative_to(self.project)
            if SKIP_DIRS & set(rel.parts):
                continue
            rel = rel.as_posix()
            self.files.append(rel)
            for t in J.parse(path.read_text(encoding='utf-8')):
                self._types[t.name] = (rel, t)
        for name, (rel, t) in self._types.items():
            owned = self._owned_names(name)
            self._add(Region(rel, name, 'class', t.start, t.end, bases=[t.extends] if t.extends else []))
            for mem in t.members:
                self._add(Region(rel, f'{name}.{mem.name}', 'method', mem.start, mem.end, owned=mem.name in owned))

    def _owned_names(self, name: str, seen=None) -> Set[str]:
        seen = seen or set()
        if name in seen or name not in self._types:
            return set()
        seen.add(name)
        base = self._types[name][1].extends
        if not base:
            return set()
        if base in self._types:
            return self._owned_names(base, seen)
        if self.owned_source == 'javap':
            return set(self._owned.get(base, set()))
        return set(J.FALLBACK_OWNED) if base.startswith('Base') else set()

    def class_owned(self, file: str, cls: str) -> Set[str]:
        return self._owned_names(cls)


def index_for(project: Path) -> CodeIndex:
    project = Path(project)
    if (project / 'pom.xml').is_file() and not (project / 'pyproject.toml').is_file():
        return JavaIndex(project)
    return CodeIndex(project)


def is_java(project: Path) -> bool:
    return (Path(project) / 'pom.xml').is_file() and not (Path(project) / 'pyproject.toml').is_file()


def _first(node) -> int:
    return min([node.lineno] + [d.lineno for d in getattr(node, 'decorator_list', [])])


def _split_camel(text: str) -> str:
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', text).replace('_', ' ')


# ------------------------------------------------------------------ 3. edits
@dataclass
class Edit:
    op: str
    file: str
    region: str = ''
    code: str = ''


def _path_rule(rel: str, allow_infra: bool) -> Optional[str]:
    if rel.startswith('/') or '..' in Path(rel).parts:
        return f'{rel}: outside the project'
    if FORBIDDEN.search(rel):
        return f'{rel}: never edited by the tool (records and secrets)'
    if DECLARATIONS.search(rel):
        return f'{rel}: versions, dependencies and the changelog are the tool\'s or the request\'s, not an edit'
    if INFRA.search(rel) and not allow_infra:
        return f'{rel}: infrastructure, CI or container file; pass --allow-infra to change it'
    return None


def _defined_names(code: str) -> List[str]:
    tree = ast.parse(textwrap.dedent(code))
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(node.name)
        elif isinstance(node, ast.ClassDef):
            names += [f'{node.name}.{i.name}' for i in node.body if isinstance(i, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return names


def check_edit(edit: Edit, plan: Dict[str, Any], index: CodeIndex, allow_infra: bool) -> Optional[str]:
    """Why this edit is refused, or None. Checked BEFORE anything is written."""
    if edit.op not in ('replace', 'add', 'create'):
        return f'unknown edit op {edit.op!r}'
    why = _path_rule(edit.file, allow_infra)
    if why:
        return why
    targets = {(t.get('file'), t.get('region')) for t in plan.get('targets', [])}
    if edit.op == 'create':
        if edit.file not in plan.get('new_files', []):
            return f'{edit.file}: not a new file of the plan'
        if (index.project / edit.file).exists():
            return f'{edit.file}: already exists'
        return None
    if (edit.file, edit.region) not in targets:
        return f'{edit.file}::{edit.region}: not in the plan'
    if not (index.project / edit.file).is_file():
        return f'{edit.file}: no such file'
    if edit.file.endswith('.java'):
        if edit.region == '<module>':
            return f'{edit.file}: Java has no module-level code; add to a class'
        names = J.java_defined_names(edit.code)
    elif not edit.file.endswith('.py'):
        return None                              # another file of the plan: whole-file regions only
    else:
        try:
            names = _defined_names(edit.code)
        except SyntaxError as e:
            return f'{edit.file}::{edit.region}: the code does not parse ({e.msg}, line {e.lineno})'
    cls = edit.region.split('.')[0] if edit.region not in ('<module>',) else ''
    region = index.regions.get(f'{edit.file}::{edit.region}')
    if edit.op == 'replace':
        if region is None or region.kind == 'class':
            return f'{edit.file}::{edit.region}: replace needs an existing method or function'
        if region.owned:
            return f'{edit.file}::{edit.region}: framework-owned; E2A runs it, the project only fills hooks'
        if edit.file.endswith('.java') and J.locate((index.project / edit.file).read_text(encoding='utf-8'),
                                                     edit.region) is None:
            return f'{edit.file}::{edit.region}: overloaded or not found; replace one member at a time'
        if len(names) < 1 or names[0].split('.')[-1] != edit.region.split('.')[-1]:
            return f'{edit.file}::{edit.region}: the code must define {edit.region.split(".")[-1]}'
    if edit.op == 'add' and edit.region != '<module>':
        if region is None or region.kind != 'class':
            return f'{edit.file}::{edit.region}: add needs a class (or <module>)'
    if cls and edit.region != '<module>':
        owned = index.class_owned(edit.file, cls)
        bad = [n for n in names if n.split('.')[-1] in owned]
        if bad:
            return f'{edit.file}::{edit.region}: defines framework-owned {sorted(bad)}'
    return None


def _indent_of(line: str) -> str:
    return line[:len(line) - len(line.lstrip())]


def apply_edits(project: Path, edits: Sequence[Edit]) -> Dict[str, str]:
    """Apply the edits; returns {file: original text or '' for a new file}. Regions are found
    again in the current text for each edit, so several edits to one file stay correct."""
    originals: Dict[str, str] = {}
    for edit in edits:
        path = Path(project) / edit.file
        if edit.op == 'create':
            originals.setdefault(edit.file, '')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(edit.code.rstrip('\n') + '\n', encoding='utf-8')
            continue
        text = path.read_text(encoding='utf-8')
        originals.setdefault(edit.file, text)
        if edit.file.endswith('.java'):
            found = J.locate(text, edit.region)
            if found is None:
                raise ChangeError(f'{edit.file}::{edit.region}: not found')
            start, end, indent, is_type = found
            lines = text.split('\n')
            code = textwrap.dedent(edit.code).strip('\n')
            if edit.op == 'replace':
                lines[start - 1:end] = textwrap.indent(code, indent).split('\n')
            else:                                # add to a type: before its closing brace
                lines[end - 1:end - 1] = [''] + textwrap.indent(code, indent).split('\n')
            new = '\n'.join(lines)
            path.write_text(new if new.endswith('\n') else new + '\n', encoding='utf-8')
            continue
        if not edit.file.endswith('.py'):        # a non-Python file of the plan: the whole file
            path.write_text(edit.code.rstrip('\n') + '\n', encoding='utf-8')
            continue
        lines = text.split('\n')
        code = textwrap.dedent(edit.code).strip('\n')
        if edit.region == '<module>':
            new = text.rstrip('\n') + '\n\n\n' + code + '\n'
        else:
            node, parent = _locate(ast.parse(text), edit.region)
            if node is None:
                raise ChangeError(f'{edit.file}::{edit.region}: not found')
            if edit.op == 'replace':
                indent = _indent_of(lines[_first(node) - 1])
                block = textwrap.indent(code, indent).split('\n')
                lines[_first(node) - 1:node.end_lineno] = block
            else:                                # add to a class: after its last line
                body_indent = _indent_of(lines[node.body[0].lineno - 1]) if node.body else '    '
                block = [''] + textwrap.indent(code, body_indent).split('\n')
                lines[node.end_lineno:node.end_lineno] = block
            new = '\n'.join(lines)
        path.write_text(new if new.endswith('\n') else new + '\n', encoding='utf-8')
    return originals


def _locate(tree: ast.Module, region: str):
    parts = region.split('.')
    scope, parent = tree.body, None
    for i, part in enumerate(parts):
        found = next((n for n in scope if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                      and n.name == part), None)
        if found is None:
            return None, None
        if i == len(parts) - 1:
            return found, parent
        parent, scope = found, found.body
    return None, None


def restore(project: Path, originals: Dict[str, str]) -> None:
    for rel, text in originals.items():
        path = Path(project) / rel
        if text == '':
            if path.exists():
                path.unlink()
        else:
            path.write_text(text, encoding='utf-8')


def diff(project: Path, originals: Dict[str, str], prefix: str = '') -> str:
    out = []
    for rel, text in originals.items():
        path = Path(project) / rel
        now = path.read_text(encoding='utf-8') if path.exists() else ''
        out += difflib.unified_diff(text.splitlines(keepends=True), now.splitlines(keepends=True),
                                    f'a/{prefix}{rel}' if text else '/dev/null', f'b/{prefix}{rel}')
    return ''.join(out)


# ------------------------------------------------------------------ 4. verification
def _conformance(project: Path) -> List[str]:
    if is_java(project):                         # e2a-java: no class may define a method the base owns
        index = JavaIndex(project)
        return sorted(f'{r.file}: {r.name} overrides a final e2a-java method' for r in index.regions.values()
                      if r.owned)
    from e2a.conformance import check_paths, failed
    src = project / 'src'
    roots = [str(src)] if src.is_dir() else [str(project)]
    findings = check_paths(roots)
    return sorted(str(f).replace(str(project) + '/', '') for f in findings if f.severity == 'error')


def _test_command(project: Path, given: Optional[str]) -> Optional[List[str]]:
    if given:
        return ['bash', '-c', given]
    if is_java(project):
        return ['mvn', '-B', '-q', 'verify'] if shutil.which('mvn') else None
    if not ((project / 'tests').is_dir() or list(project.glob('test_*.py'))):
        return None
    return [sys.executable, '-m', 'pytest', '-q', '-x', '-p', 'no:cacheprovider']


def run_tests(project: Path, command: Optional[List[str]], timeout: int = 900) -> Tuple[Optional[bool], str]:
    if command is None:
        return None, 'no tests found'
    env = dict(os.environ)
    src = project / 'src'
    env['PYTHONPATH'] = os.pathsep.join([p for p in (str(src) if src.is_dir() else str(project),
                                                     env.get('PYTHONPATH', '')) if p])
    try:
        proc = subprocess.run(command, cwd=project, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return False, f'tests timed out after {timeout} s'
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, out[-3000:]


def verify(project: Path, changed: List[str], baseline_conformance: List[str],
           test_cmd: Optional[List[str]]) -> Dict[str, Any]:
    from generator_critic_agent import GeneratorCriticAgent
    checks: Dict[str, Any] = {}
    failures: List[str] = []
    compile_errors = []
    for rel in changed:
        path = project / rel
        if rel.endswith('.py') and path.exists():
            try:
                compile(path.read_text(encoding='utf-8'), rel, 'exec')
            except SyntaxError as e:
                compile_errors.append(f'{rel}:{e.lineno}: {e.msg}')
    java = is_java(project)
    if java and not test_cmd and any(r.endswith('.java') for r in changed):
        ok, out = run_tests(project, ['mvn', '-B', '-q', '-DskipTests', 'test-compile']
                            if shutil.which('mvn') else None)
        if ok is False:
            compile_errors.append(out[-1500:])
    checks['compile'] = ('passed' if not compile_errors else compile_errors) if not (java and test_cmd) \
        else 'with the tests (Maven)'
    failures += [f'compile: {e}' for e in compile_errors]
    if not compile_errors:
        new = sorted(set(_conformance(project)) - set(baseline_conformance))
        checks['conformance'] = 'passed' if not new else new
        failures += [f'conformance: {f}' for f in new]
    secrets = []
    for rel in changed:
        path = project / rel
        if path.exists():
            text = path.read_text(encoding='utf-8', errors='replace')
            secrets += [f'{rel}: {name}' for name, pattern in SECRET_PATTERNS if pattern.search(text)]
    checks['secret_scan'] = 'passed' if not secrets else secrets
    failures += [f'secret scan: {s}' for s in secrets]
    critic = GeneratorCriticAgent()
    concurrency = []
    for rel in changed:
        path = project / rel
        if rel.endswith('.py') and path.exists() and not compile_errors:
            concurrency += [f'{rel}: {f}' for f in critic.concurrency_findings(path.read_text(encoding='utf-8'))]
        elif rel.endswith('.java') and path.exists():
            text = path.read_text(encoding='utf-8')
            concurrency += [f'{rel}: {msg}' for pattern, msg in J.JAVA_CRITIC if pattern.search(text)]
    checks['critic_concurrency'] = 'passed' if not concurrency else concurrency
    failures += [f'critic: {c}' for c in concurrency]
    if not failures:
        ok, out = run_tests(project, test_cmd)
        checks['tests'] = 'passed' if ok else ('not run: ' + out if ok is None else 'failed')
        if ok is False:
            failures.append('tests failed:\n' + out)
    return {'passed': not failures, 'checks': checks, 'failures': failures}


# ------------------------------------------------------------------ the model
def _json_answer(text: str) -> Dict[str, Any]:
    text = (text or '').strip()
    fence = re.search(r'```(?:json)?\s*(.*?)```', text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end < start:
        raise ChangeError(f'the model did not answer with JSON: {text[:200]!r}')
    try:
        return json.loads(text[start:end + 1])
    except ValueError as e:
        raise ChangeError(f'the model answered invalid JSON: {e}') from e


def replay_llm(path: Path):
    """Recorded answers, in call order (a JSON list of strings or objects)."""
    from e2a_simulated_llm import SimulatedLLMService
    answers = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(answers, list):
        raise ChangeError(f'{path}: a JSON list of answers')
    queue = [a if isinstance(a, str) else json.dumps(a) for a in answers]

    def next_answer(messages, ctx):
        if not queue:
            raise ChangeError(f'{path}: no recorded answer left')
        return queue.pop(0)
    return SimulatedLLMService(default_response=next_answer)


def bind_llm(spec: Optional[str]):
    """(service, model label) from --llm: replay:<file>, profile:<name> or a bare profile name."""
    spec = spec or os.environ.get('E2A_PROVIDER_PROFILE', '')
    if not spec:
        raise ChangeError('no model: pass --llm profile:<name> (an E2A provider profile) or replay:<file>, '
                          'or set E2A_PROVIDER_PROFILE')
    if spec.startswith('replay:'):
        return replay_llm(Path(spec[len('replay:'):])), 'replay'
    name = spec[len('profile:'):] if spec.startswith('profile:') else spec
    from e2a.bindings import bindings_from_profile
    bindings = bindings_from_profile(name)
    try:
        model = bindings.setting('model_id') or name
    except (KeyError, AttributeError, ValueError):
        model = name
    return bindings.get('llm_service'), str(model)


class Model:
    def __init__(self, service, label: str, record: Optional[Path] = None) -> None:
        self.service, self.label, self.record = service, label, record
        self.answers: List[str] = []

    def ask(self, system: str, user: str) -> Dict[str, Any]:
        out = run_coro_sync(self.service.process_inference(
            [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}], tenant_id='aidlc-change'))
        if out.get('status') != 'SUCCESS':
            raise ChangeError(f"model call failed: {out.get('error', out.get('status'))}")
        text = out.get('text', '')
        self.answers.append(text)
        if self.record:
            self.record.write_text(json.dumps(self.answers, indent=2) + '\n', encoding='utf-8')
        return _json_answer(text)


# ------------------------------------------------------------------ 2. the plan
def make_plan(model: Model, index: CodeIndex, prompt: str, target: Optional[str],
              kind: Optional[str]) -> Dict[str, Any]:
    if target:
        file, _, region = target.partition('::')
        found = index.regions.get(f'{file}::{region}')
        if found is None:
            raise ChangeError(f'--target {target}: not found in the project')
        if found.owned:
            raise ChangeError(f'--target {target}: framework-owned; change a hook instead')
        candidates = [found]
    else:
        candidates = index.candidates(prompt)
    listing = '\n'.join(f'- {r.ref()} ({r.kind}{", framework-owned" if r.owned else ""})'
                        f'{": " + r.doc if r.doc else ""}' for r in candidates)
    user = (f'Change request:\n{prompt}\n\nCandidate regions:\n{listing}\n\n'
            f'Project files:\n' + '\n'.join(f'- {f}' for f in index.files[:200]) +
            (f'\n\nThe developer named the target {target}; plan around it.' if target else '') +
            (f'\n\nThe developer says the kind is {kind}.' if kind else ''))
    plan = model.ask(PLAN_SYSTEM, user)
    plan['kind'] = kind or plan.get('kind')
    if plan['kind'] not in CHANGE_KINDS:
        raise ChangeError(f"the plan's kind {plan['kind']!r} is not one of {CHANGE_KINDS}")
    for key in ('subject', 'targets'):
        if not plan.get(key):
            raise ChangeError(f'the plan has no {key}')
    plan.setdefault('new_files', [])
    plan.setdefault('declaration_changes', [])
    plan.setdefault('body', plan.get('summary', ''))
    plan.setdefault('changelog', plan.get('summary', plan['subject']))
    return plan


def show_plan(plan: Dict[str, Any], change: str) -> str:
    lines = [f'Change {change}: {plan["subject"]} ({plan["kind"]})', '', plan.get('summary', ''), '', 'Targets:']
    lines += [f'  - {t.get("file")}::{t.get("region")}  {t.get("why", "")}' for t in plan['targets']]
    if plan['new_files']:
        lines += ['New files:'] + [f'  - {f}' for f in plan['new_files']]
    lines += ['', f'Changelog: {plan.get("changelog", "")}']
    return '\n'.join(lines)


def check_plan(plan: Dict[str, Any], index: CodeIndex, allow_infra: bool) -> List[str]:
    problems = [f'declaration change: {d}' for d in plan.get('declaration_changes') or []]
    for t in plan['targets']:
        rel, region = t.get('file', ''), t.get('region', '')
        why = _path_rule(rel, allow_infra)
        if why:
            problems.append(why)
            continue
        found = index.regions.get(f'{rel}::{region}')
        if rel.endswith('.py') and region != '<module>' and found is None:
            problems.append(f'{rel}::{region}: not found')
        elif found is not None and found.owned:
            problems.append(f'{rel}::{region}: framework-owned')
    for rel in plan.get('new_files', []):
        why = _path_rule(rel, allow_infra)
        if why:
            problems.append(why)
    return problems


def _sources(index: CodeIndex, plan: Dict[str, Any]) -> str:
    out = []
    for rel in dict.fromkeys(t['file'] for t in plan['targets']):
        path = index.project / rel
        if path.is_file():
            text = path.read_text(encoding='utf-8')
            out.append(f'=== {rel}\n{text}')
            if rel.endswith(('.py', '.java')):
                for cls in {t['region'].split('.')[0] for t in plan['targets'] if t['file'] == rel and t['region'] != '<module>'}:
                    owned = sorted(index.class_owned(rel, cls))
                    if owned:
                        out.append(f'(framework-owned in {cls}, never define: {", ".join(owned)})')
    return '\n\n'.join(out)


# ------------------------------------------------------------------ the command
def change(args: argparse.Namespace, out=print, ask=input) -> Dict[str, Any]:
    project = Path(args.project).resolve()
    if not project.is_dir():
        raise ChangeError(f'{project}: no such project')
    prompt = args.prompt or (Path(args.prompt_file).read_text(encoding='utf-8') if args.prompt_file else '')
    if not prompt.strip():
        raise ChangeError('no change request: pass --prompt or --prompt-file')
    if args.kind and args.kind not in CHANGE_KINDS:
        raise ChangeError(f'--kind must be one of {CHANGE_KINDS}')
    run = start_run(project, kind=args.kind or 'feature', author=args.author, reuse_branch=True,
                    change_parts=[project.name, prompt], branch=f'aidlc-change/{project.name}/{{change}}')
    if run.git.branch_exists(run.branch):
        return {'success': True, 'reused': True, 'change_id': run.change, 'branch': run.branch,
                'message': f'this change was already made on {run.branch}; review or merge it there'}
    service, label = bind_llm(args.llm)
    model = Model(service, args.model_id or label, Path(args.record) if args.record else None)
    test_cmd = None if args.no_tests else _test_command(project, args.test_command)
    if test_cmd is not None:
        ok, output = run_tests(project, test_cmd)
        if ok is False:
            raise ChangeError('the project\'s tests already fail on the base commit; fix them first:\n' + output)
    baseline = _conformance(project)
    index = index_for(project)
    plan = make_plan(model, index, prompt, args.target, args.kind)
    run.kind = plan['kind']
    problems = check_plan(plan, index, args.allow_infra)
    if problems:
        abandon_run(run, model=model.label, outcome='refused', reason='; '.join(problems), stream=_stderr)
        hint = (' Declare it in the request and run `aidlc-build --upgrade --request <file> --commit`, then '
                'run aidlc-change for the logic.' if plan.get('declaration_changes') else '')
        raise ChangeError('the plan cannot be carried out: ' + '; '.join(problems) + hint)
    out(show_plan(plan, run.change))
    if not args.yes:
        if not sys.stdin.isatty() and ask is input:
            raise ChangeError('confirm the plan interactively, or pass --yes (the workflow does; the pull request '
                              'review is the confirmation there)')
        if ask('Go ahead with this plan? [y/N] ').strip().lower() not in ('y', 'yes'):
            abandon_run(run, model=model.label, outcome='declined', reason='the developer declined the plan',
                        stream=_stderr)
            return {'success': False, 'declined': True, 'change_id': run.change}
    run.git.switch_new(run.branch)
    failures: List[str] = []
    attempts: List[Dict[str, Any]] = []
    originals: Dict[str, str] = {}
    result: Dict[str, Any] = {}
    for attempt in range(1, args.max_attempts + 1):
        user = (f'Approved plan:\n{json.dumps(plan, indent=2)}\n\nCurrent sources:\n{_sources(index, plan)}'
                + (f'\n\nYour previous attempt failed these checks; fix them:\n' + '\n'.join(failures)
                   if failures else ''))
        try:
            answer = model.ask(EDIT_SYSTEM, user)
            edits = [Edit(e.get('op', ''), e.get('file', ''), e.get('region', ''), e.get('code', ''))
                     for e in answer.get('edits', [])]
            if not edits:
                raise ChangeError('the model proposed no edits')
            refused = [why for why in (check_edit(e, plan, index, args.allow_infra) for e in edits) if why]
            if refused:
                failures = [f'refused edit: {r}' for r in refused]
                attempts.append({'attempt': attempt, 'failures': failures})
                continue
            originals = apply_edits(project, edits)
        except (ChangeError, SyntaxError) as e:
            failures = [str(e)]
            attempts.append({'attempt': attempt, 'failures': failures})
            continue
        result = verify(project, list(originals), baseline, test_cmd)
        attempts.append({'attempt': attempt, 'failures': result['failures']})
        if result['passed']:
            break
        failures = result['failures']
        last = diff(project, originals, run.rel(project) + '/')
        restore(project, originals)
        originals, result['patch'] = {}, last
    if not result.get('passed'):
        return _give_up(run, model, project, plan, attempts, result.get('patch', ''))
    changed = [run.rel(project / rel) for rel in originals]
    before = {run.rel(project / rel): (sha256(text) if text else None) for rel, text in originals.items()}
    committed = finish_run(
        run, subject=plan['subject'], body=plan.get('body', ''), model=model.label, files=changed, before=before,
        prompt=prompt, plan={k: plan[k] for k in ('summary', 'kind', 'targets', 'new_files') if k in plan},
        verification={'checks': result['checks'], 'attempts': attempts}, changelog_line=plan.get('changelog', ''),
        origin='changed', signoff=args.signoff, stream=_stderr)
    report = {'success': True, **committed, 'plan': plan['subject'], 'checks': result['checks'],
              'attempts': len(attempts)}
    if args.pr:
        report['pull_request'] = _open_pr(run, plan, committed, result['checks'])
    return report


def _give_up(run, model, project: Path, plan, attempts, patch: str) -> Dict[str, Any]:
    root = run.repo_root
    (root / 'aidlc-change.patch').write_text(patch or '', encoding='utf-8')
    report = {'success': False, 'change_id': run.change, 'plan': plan, 'attempts': attempts,
              'patch': 'aidlc-change.patch', 'message': 'verification failed after every attempt; nothing was '
              'committed. The last attempt is in aidlc-change.patch for you to review or finish by hand.'}
    (root / 'aidlc-change-report.json').write_text(json.dumps(report, indent=2, default=str) + '\n', encoding='utf-8')
    abandon_run(run, model=model.label, outcome='failed verification',
                reason='; '.join(attempts[-1]['failures'])[:500] if attempts else '', stream=_stderr)
    return report


def _open_pr(run, plan, committed, checks) -> Dict[str, Any]:
    if not shutil.which('gh'):
        return {'opened': False, 'how': f'git push -u origin {run.branch} && gh pr create --head {run.branch}'}
    push = subprocess.run(['git', '-C', str(run.repo_root), 'push', '-u', 'origin', run.branch],
                          capture_output=True, text=True)
    if push.returncode != 0:
        return {'opened': False, 'error': push.stderr.strip()[-500:]}
    body = (f"{plan.get('summary', '')}\n\n**Plan**\n" +
            '\n'.join(f"- `{t['file']}::{t['region']}`: {t.get('why', '')}" for t in plan['targets']) +
            f"\n\n**Checks**\n" + '\n'.join(f'- {k}: {v if isinstance(v, str) else "see the change record"}'
                                          for k, v in checks.items()) +
            f"\n\n**Change record** `{committed['change_record']}`\n\n"
            'Made with aidlc-change (A2C). Merge or rebase; a squash merge must keep the commit trailers.')
    proc = subprocess.run(['gh', 'pr', 'create', '--head', run.branch, '--base', run.start_branch,
                           '--title', plan['subject'], '--body', body], cwd=run.repo_root, capture_output=True, text=True)
    return {'opened': proc.returncode == 0, 'url': proc.stdout.strip(), 'error': proc.stderr.strip()[-500:]}


def _stderr(line: str) -> None:
    print(line, file=sys.stderr)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='aidlc-change', description=__doc__.split('\n')[0])
    p.add_argument('--project', required=True, help='the project folder (with src/ and tests/)')
    p.add_argument('--prompt', help='the change request')
    p.add_argument('--prompt-file', help='the change request, from a file')
    p.add_argument('--target', help='path::Class.method (relative to the project) to change')
    p.add_argument('--kind', choices=CHANGE_KINDS, help='feature | fix | refactor | breaking (else the plan proposes)')
    p.add_argument('--llm', help='profile:<E2A provider profile> or replay:<answers.json> (default: E2A_PROVIDER_PROFILE)')
    p.add_argument('--model-id', help='the model name recorded in the trailer and the change record')
    p.add_argument('--record', help='save the model\'s answers to this file, for replay')
    p.add_argument('--test-command', help='how to run the project\'s tests (default: pytest with src/ on the path)')
    p.add_argument('--no-tests', action='store_true', help='do not run the tests (the project CI still does)')
    p.add_argument('--max-attempts', type=int, default=MAX_ATTEMPTS)
    p.add_argument('--allow-infra', action='store_true', help='allow Terraform, CI and container files in the plan')
    p.add_argument('--author', help='locally: "Name <email>"; the email must be your git identity')
    p.add_argument('--signoff', action='store_true', help='add your Signed-off-by (never added on its own)')
    p.add_argument('--yes', action='store_true', help='do not ask to confirm the plan (the workflow)')
    p.add_argument('--pr', action='store_true', help='push the branch and open the pull request (gh)')
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        report = change(args, out=_stderr)        # the plan on stderr: stdout is only the JSON result
    except (ChangeError, ProvenanceError) as error:
        print(json.dumps({'success': False, 'error': str(error)}, indent=2))
        return 1
    print(json.dumps({k: v for k, v in report.items() if k != 'audit'}, indent=2, default=str))
    return 0 if report.get('success') else 1


if __name__ == '__main__':
    sys.exit(main())
