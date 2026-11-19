"""Java support for aidlc-change (A2C v1.5.1, hub design note AD-01, plan step 3).

A light structural reader for Java sources, enough to index and edit at member level:
comments and literals are masked, type declarations and their members are found by brace
matching, and a member's region starts at its Javadoc (or annotations) and ends at its closing
brace. The methods e2a-java owns are its `final` methods, read with `javap` from the e2a-java jars
the project's pom.xml names (in the local Maven repository); without them A2C's older rule
applies (`run`, `execute`, `retrieve` on a `Base*` class). The compiler enforces `final` as well,
and Maven compiles and tests every change.
"""
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

__all__ = ['mask', 'JavaType', 'JavaMember', 'parse', 'e2a_java_owned', 'java_defined_names', 'locate',
           'FALLBACK_OWNED', 'JAVA_CRITIC']

FALLBACK_OWNED = {'run', 'execute', 'retrieve'}
_TYPE = re.compile(r'\b(class|interface|enum|record)\s+([A-Za-z_]\w*)')
_MODIFIERS = {'public', 'protected', 'private', 'static', 'final', 'abstract', 'synchronized', 'native',
              'default', 'strictfp', 'transient', 'volatile', 'sealed', 'non-sealed'}
_NOT_METHODS = {'if', 'for', 'while', 'switch', 'catch', 'new', 'return', 'throw', 'synchronized', 'super', 'this'}
# the Java side of the critic's rule: the model is called only through e2a-java's LLM service
JAVA_CRITIC = [
    (re.compile(r'^\s*import\s+(?:com\.openai|com\.anthropic|com\.google\.cloud\.vertexai|'
                r'software\.amazon\.awssdk\.services\.bedrockruntime)\b', re.M),
     'direct provider SDK import: the model is called only through the bound LLM service'),
    (re.compile(r'\bnew\s+(?:Semaphore|RateLimiter)\s*\('),
     'own semaphore or rate limiter: capacity is enforced by the LLM service'),
]


def mask(text: str) -> str:
    """Comments, string, char and text-block literals replaced by spaces (newlines kept)."""
    out, i, n = list(text), 0, len(text)

    def blank(a, b):
        for k in range(a, b):
            if out[k] != '\n':
                out[k] = ' '
    while i < n:
        if text.startswith('//', i):
            j = text.find('\n', i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif text.startswith('/*', i):
            j = text.find('*/', i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
        elif text.startswith('"""', i):
            j = text.find('"""', i + 3)
            j = n if j < 0 else j + 3
            blank(i + 1, j - 1)
            i = j
        elif text[i] in '"\'':
            q, j = text[i], i + 1
            while j < n and text[j] != q and text[j] != '\n':
                j += 2 if text[j] == '\\' else 1
            blank(i + 1, min(j, n))
            i = j + 1
        else:
            i += 1
    return ''.join(out)


def _close(m: str, open_at: int) -> int:
    depth = 0
    for k in range(open_at, len(m)):
        if m[k] == '{':
            depth += 1
        elif m[k] == '}':
            depth -= 1
            if depth == 0:
                return k
    return len(m) - 1


def _line(text: str, offset: int) -> int:
    return text.count('\n', 0, offset) + 1


@dataclass
class JavaMember:
    name: str
    start: int          # line of its Javadoc, annotations or first modifier
    end: int            # line of its closing brace (or ';')
    final: bool


@dataclass
class JavaType:
    name: str           # Outer or Outer.Inner
    kind: str
    extends: str
    start: int
    end: int            # line of the closing brace
    body_indent: str
    members: List[JavaMember]


def _leading_doc(text: str, m: str, at: int) -> int:
    """Move a member's start back over its Javadoc / comment, if one sits right above it."""
    before = text[:at].rstrip()
    if before.endswith('*/'):
        start = text.rfind('/*', 0, len(before))
        if start >= 0 and not m[start:len(before)].strip():
            return start
    return at


def parse(text: str) -> List[JavaType]:
    m = mask(text)
    types: List[JavaType] = []

    def walk(lo: int, hi: int, prefix: str) -> None:
        for match in _TYPE.finditer(m, lo, hi):
            if any(t_lo <= match.start() <= t_hi for t_lo, t_hi in taken):
                continue
            brace = m.find('{', match.end(), hi)
            semi = m.find(';', match.end(), hi)
            if brace < 0 or (0 <= semi < brace and match.group(1) != 'record'):
                continue
            close = _close(m, brace)
            taken.append((match.start(), close))
            header = m[match.end():brace]
            ext = re.search(r'\bextends\s+([\w.]+)', header)
            name = f'{prefix}{match.group(2)}'
            members, nested = _members(text, m, brace + 1, close)
            first = m[brace + 1:close]
            indent_line = next((l for l in first.split('\n')[1:] if l.strip()), '    ')
            types.append(JavaType(name, match.group(1), ext.group(1).split('.')[-1] if ext else '',
                                  _line(text, _decl_start(m, match.start())), _line(text, close),
                                  indent_line[:len(indent_line) - len(indent_line.lstrip())], members))
            for n_lo, n_hi in nested:
                walk(n_lo, n_hi, name + '.')
    taken: List[Tuple[int, int]] = []
    walk(0, len(m), '')
    return types


def _decl_start(m: str, at: int) -> int:
    line_start = m.rfind('\n', 0, at) + 1
    return line_start + (len(m[line_start:at]) - len(m[line_start:at].lstrip()))


def _members(text: str, m: str, lo: int, hi: int) -> Tuple[List[JavaMember], List[Tuple[int, int]]]:
    """Members at depth 1 of a type body: methods (with bodies or abstract) and nested types."""
    members, nested, k, start = [], [], lo, None
    while k < hi:
        ch = m[k]
        if start is None and not ch.isspace() and ch not in ';}':
            start = k
        if ch == ';' and start is not None:
            header = m[start:k]
            name = _method_name(header)
            if name:
                members.append(JavaMember(name, _line(text, _leading_doc(text, m, start)), _line(text, k),
                                          bool(re.search(r'\bfinal\b', header.split('(')[0]))))
            start = None
        elif ch == '{' and start is not None:
            close = _close(m, k)
            header = m[start:k]
            if _TYPE.search(header) and '(' not in header.split('=')[0].split(_TYPE.search(header).group(0))[0]:
                nested.append((start, close + 1))
            else:
                name = _method_name(header)
                if name:
                    members.append(JavaMember(name, _line(text, _leading_doc(text, m, start)), _line(text, close),
                                              bool(re.search(r'\bfinal\b', header.split('(')[0]))))
                elif '=' in header:                    # a field with an initializer block, e.g. a lambda
                    end = m.find(';', close, hi)
                    close = end if end >= 0 else close
            k, start = close + 1, None
            continue
        k += 1
    return members, nested


def _method_name(header: str) -> Optional[str]:
    head = re.sub(r'@\w+(?:\.\w+)*(?:\s*\([^)]*\))?', ' ', header)       # annotations
    paren = head.find('(')
    if paren < 0 or '=' in head[:paren] or '->' in head[:paren]:
        return None
    before = head[:paren].split()
    if not before:
        return None
    name = before[-1]
    if not re.fullmatch(r'[A-Za-z_]\w*', name) or name in _NOT_METHODS or name in _MODIFIERS:
        return None
    return name


def java_defined_names(code: str) -> List[str]:
    """The methods a fragment defines (a member, several members, or a whole class)."""
    types = parse(code)
    if types:
        return [mem.name for t in types for mem in t.members]
    wrapped = 'class __Fragment {\n' + code + '\n}\n'
    return [mem.name for t in parse(wrapped) for mem in t.members]


def locate(text: str, region: str) -> Optional[Tuple[int, int, str, bool]]:
    """(start line, end line, indent, is_type) of `Type`, `Type.method` or `Outer.Inner.method`."""
    types = parse(text)
    by_name = {t.name: t for t in types}
    if region in by_name:
        t = by_name[region]
        return t.start, t.end, t.body_indent, True
    owner, _, member = region.rpartition('.')
    t = by_name.get(owner)
    if t is None:
        return None
    found = [mem for mem in t.members if mem.name == member]
    if len(found) != 1:                       # overloads: replace the type's member by a whole-type edit
        return None
    lines = text.split('\n')
    line = lines[found[0].start - 1]
    return found[0].start, found[0].end, line[:len(line) - len(line.lstrip())], False


# ------------------------------------------------------------------ what e2a-java owns
def _e2a_jars(project: Path) -> List[Path]:
    pom = Path(project) / 'pom.xml'
    if not pom.is_file():
        return []
    text = pom.read_text(encoding='utf-8')
    repo = Path(os.environ.get('MAVEN_REPOSITORY', Path.home() / '.m2' / 'repository'))
    jars = []
    for artifact, version in re.findall(r'<groupId>com\.subhamviky\.e2a</groupId>\s*<artifactId>([\w.-]+)'
                                        r'</artifactId>\s*<version>([^<]+)</version>', text):
        jar = repo / 'com' / 'subhamviky' / 'e2a' / artifact / version / f'{artifact}-{version}.jar'
        if jar.is_file():
            jars.append(jar)
    return jars


def e2a_java_owned(project: Path) -> Optional[Dict[str, Set[str]]]:
    """Simple class name -> its final methods, inherited ones included. None if javap or the jars
    are not available (the caller then applies FALLBACK_OWNED and relies on the compiler)."""
    jars = _e2a_jars(project)
    if not jars or not shutil.which('javap'):
        return None
    classes = []
    for jar in jars:
        with zipfile.ZipFile(jar) as z:
            classes += [n[:-6].replace('/', '.') for n in z.namelist()
                        if n.startswith('com/subhamviky/e2a/') and n.endswith('.class') and '$' not in n]
    if not classes:
        return None
    proc = subprocess.run(['javap', '-protected', '-cp', os.pathsep.join(map(str, jars)), *classes],
                          capture_output=True, text=True)
    own: Dict[str, Set[str]] = {}
    parent: Dict[str, str] = {}
    current = None
    for line in proc.stdout.splitlines():
        decl = re.match(r'^\S.*\b(?:class|interface)\s+([\w.$]+)(?:<[^{]*?>)?(?:\s+extends\s+([\w.$]+))?', line)
        if decl and line.rstrip().endswith('{'):
            current = decl.group(1).split('.')[-1]
            own.setdefault(current, set())
            if decl.group(2):
                parent[current] = decl.group(2).split('.')[-1].split('<')[0]
            continue
        if current and '(' in line and re.search(r'\bfinal\b', line.split('(')[0]):
            own[current].add(line.split('(')[0].split()[-1])
    resolved: Dict[str, Set[str]] = {}
    for name in own:
        names, seen, k = set(), set(), name
        while k and k not in seen:
            seen.add(k)
            names |= own.get(k, set())
            k = parent.get(k)
        resolved[name] = names
    return resolved
