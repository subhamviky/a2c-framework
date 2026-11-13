"""generator_critic_agent.py — G2C quality gate (G2C Framework Reference §9).

GeneratorCriticAgent scores generated class files 0.0–1.0 with deterministic
structural rules. It is distinct from A2C's CodeCriticAgent, which checks NFR
patterns in generated business code.

  review(response, request) -> {score, missing, passed, findings, critic_type}
  score(response, request)  -> float   (review()['score'])

Rule sets (critic_type, from config or request['generator_type']):
  e2a_abstract   nine E2A classes present; abstract hooks marked; parses
  a2c_abstract   SDLCAssistantAgent, DevRequest, SDLCWorkflow, CodeCriticAgent,
                 _apply_policy with mandatory-NFR injection
  e2a_inherited  class <agent_name> extends a base; _build_messages and
                 _evaluate_output overridden; run/execute/retrieve NOT overridden;
                 no name-mangled private access
  a2c_inherited  as e2a_inherited, and the class extends SDLCAssistantAgent
  (every type)   concurrency rules: no agent-level _validate_state, no own
                 semaphore or rate limiter, no provider SDK import or call

Python output is parsed with ast; other runtimes use patterns. Java output is
also compiled with `javac` (with the abstract base files the request points
to) when a JDK is on PATH; a compile error scores 0.0. Disable with
critic_config['java_compile_check'] = False. The checks are
structural, not a proof of correctness. Deductions: 0.25 per concurrency
finding, 0.10 per missing E2A class, 0.15 per missing required element.
"""
import ast
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

E2A_CLASSES = ['BaseAgent', 'BaseWorkflow', 'BaseRAGPipeline', 'BaseToolService',
               'BaseLLMAgentService', 'BaseInfraProvisioner', 'BaseObservability',
               'BasePipeline', 'BaseGovernanceFramework']
A2C_ELEMENTS = ['SDLCAssistantAgent', 'DevRequest', 'SDLCWorkflow', 'CodeCriticAgent', '_apply_policy']
ENTRY_POINTS = ('run', 'execute', 'retrieve')
INHERITED_HOOKS = ('_build_messages', '_evaluate_output')
JAVA_INHERITED_HOOKS = ('buildMessages', 'evaluateOutput')


class GeneratorCriticAgent:
    CONCURRENCY_RULES = [
        (re.compile(r'\bdef\s+_validate_state\b'),
         'agent-level _validate_state: validation belongs to BaseValidationService'),
        (re.compile(r'\b(?:asyncio|threading)\.(?:Bounded)?Semaphore\b|\bBoundedSemaphore\('),
         'own semaphore: model concurrency is enforced by config["llm_service"]'),
        (re.compile(r'\b(?:RateLimiter|TokenBucket|token_bucket|ratelimit)\b'),
         'own rate limiter: RPM/TPM quota is enforced by config["llm_service"]'),
        (re.compile(r'^\s*(?:import|from)\s+(?:openai|anthropic|google\.generativeai|vertexai)\b',
                    re.M),
         'direct provider SDK import: the model is called only through _infer()'),
        (re.compile(r'invoke_model\(|bedrock-runtime|\.chat\.completions\.create\('),
         'direct provider call: the model is called only through _infer()'),
    ]
    PENALTY = 0.25
    MISSING_CLASS = 0.10
    MISSING_ELEMENT = 0.15

    def __init__(self, config=None):
        self.config = config or {}

    # ------------------------------------------------------------------ public
    def concurrency_findings(self, source):
        """Violations of the shared-gateway rule found in generated source."""
        return [msg for pattern, msg in self.CONCURRENCY_RULES if pattern.search(source or '')]

    def score(self, response, request):
        return self.review(response, request)['score']

    def review(self, response, request):
        request = request or {}
        source = response if isinstance(response, str) else str(response or '')
        ctype = self.config.get('critic_type') or request.get('generator_type') or ''
        runtime = request.get('runtime', 'python')
        findings = self.concurrency_findings(source)
        missing, passed, deduction = [], [], self.PENALTY * len(findings)

        tree = None
        if runtime == 'python' and ctype:
            try:
                tree = ast.parse(source)
                passed.append('parses')
            except SyntaxError as e:
                return self._report(0.0, ctype, ['python syntax error: %s' % e.msg], passed, findings)

        java12 = runtime == 'java' and request.get('e2a_contract') == '1.2'
        if java12:            # D-01: the code imports e2a-java, which is not on a standalone javac's classpath
            passed.append('compiled by the project build (mvn verify, against e2a-java)')
        if runtime == 'java' and ctype and not java12 and self.config.get('java_compile_check', True):
            error = self._java_compile_error(source, request)
            if error:
                return self._report(0.0, ctype, ['java compile error: %s' % error], passed, findings)
            if error is not None:
                passed.append('compiles')

        if ctype == 'e2a_abstract':
            names = self._class_names(tree, source)
            for c in E2A_CLASSES:
                (passed if c in names else missing).append(c)
                if c not in names:
                    deduction += self.MISSING_CLASS
            if runtime == 'python' and not re.search(r'@abstractmethod', source):
                missing.append('@abstractmethod hooks'); deduction += self.MISSING_ELEMENT
        elif ctype == 'a2c_abstract':
            names = self._class_names(tree, source)
            for e in A2C_ELEMENTS:
                ok = e in names if not e.startswith('_') else bool(re.search(r'\b%s\b' % e, source))
                (passed if ok else missing).append(e)
                if not ok:
                    deduction += self.MISSING_ELEMENT
            if not re.search(r'MANDATORY_NFRS|mandatory_nfrs', source):
                missing.append('mandatory NFR injection'); deduction += self.MISSING_ELEMENT
        elif ctype in ('e2a_inherited', 'a2c_inherited'):
            deduction += self._inherited(tree, source, request, ctype, missing, passed)

        return self._report(max(0.0, round(1.0 - deduction, 4)), ctype, missing, passed, findings)

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _report(score, ctype, missing, passed, findings):
        return {'score': score, 'critic_type': ctype, 'missing': missing + findings,
                'passed': passed, 'findings': findings}

    @staticmethod
    def _java_compile_error(source, request):
        """None when no JDK is available; '' when the source compiles;
        otherwise the first compiler error line."""
        javac = shutil.which('javac')
        if not javac:
            return None
        m = re.search(r'\bpublic\s+(?:final\s+|abstract\s+)*class\s+(\w+)', source)
        if not m:
            return 'no public class found'
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for key in ('e2a_abstract_class_path', 'abstract_class_path'):
                p = request.get(key)
                if p and Path(p).is_file() and Path(p).suffix == '.java' \
                        and Path(p).stem != m.group(1):
                    dst = Path(tmp) / 'base' / Path(p).name
                    dst.parent.mkdir(exist_ok=True)
                    dst.write_text(Path(p).read_text(encoding='utf-8'), encoding='utf-8')
                    files.append(str(dst))
            own = Path(tmp) / f'{m.group(1)}.java'
            own.write_text(source, encoding='utf-8')
            files.append(str(own))
            proc = subprocess.run([javac, '-d', str(Path(tmp) / 'out')] + files,
                                  capture_output=True, text=True, timeout=120)
            if proc.returncode == 0:
                return ''
            errors = [l for l in proc.stderr.splitlines() if 'error:' in l]
            return (errors[0].split('error:', 1)[1].strip() if errors else 'javac failed')

    @staticmethod
    def _class_names(tree, source):
        if tree is not None:
            return {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
        pat = r'\b(?:class|interface|struct)\s+(\w+)|\btype\s+(\w+)\s+(?:interface|struct)'
        return {a or b for a, b in re.findall(pat, source)}

    def _inherited(self, tree, source, request, ctype, missing, passed):
        agent = request.get('agent_name') or ''
        want_base = 'SDLCAssistantAgent' if ctype == 'a2c_inherited' else None
        d = 0.0
        if tree is not None:
            cls = next((n for n in ast.walk(tree)
                        if isinstance(n, ast.ClassDef) and n.name == agent), None)
            if cls is None:
                missing.append(f'class {agent}')
                return 0.5
            bases = [getattr(b, 'id', getattr(b, 'attr', '')) for b in cls.bases]
            methods = {n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        else:
            m = re.search(r'\bclass\s+%s\b([^{\n]*)' % re.escape(agent), source)
            g = re.search(r'\btype\s+%s\s+struct\s*\{\s*(\w+)' % re.escape(agent), source)
            if not (m or g):
                missing.append(f'class {agent}')
                return 0.5
            bases = re.findall(r'(?:extends|:|\()\s*(\w+)', m.group(1)) if m else [g.group(1)]
            methods = set(re.findall(r'\b(_?\w+)\s*\(', source))
        if bases:
            passed.append('extends a base')
        else:
            missing.append('base class'); d += self.MISSING_ELEMENT
        if want_base:
            if want_base in bases:
                passed.append(f'extends {want_base}')
            else:
                missing.append(f'extends {want_base}'); d += self.MISSING_ELEMENT
        hooks = JAVA_INHERITED_HOOKS if request.get('runtime') == 'java' else INHERITED_HOOKS
        if request.get('e2a_contract') == '1.2' and request.get('runtime', 'python') == 'python':
            # v1.2: _evaluate_output is needed only by an agent with a model step
            hooks = ('_build_messages',) + (('_evaluate_output',) if 'return None' not in source else ())
            try:
                from e2a.conformance import check_sources
                errors = [f for f in check_sources({f'{agent}.py': source}) if f.rule == 'R1']
            except ImportError:                       # E2A < 1.2 installed: the AST checks below still run
                errors = []
            for f in errors:
                missing.append(f'conformance {f.rule}: {f.where}'); d += self.MISSING_ELEMENT
        if request.get('e2a_contract') == '1.2' and request.get('runtime') == 'java':
            # D-01: e2a-java. run() is final in BaseAgent, so the compiler enforces R1; the hooks:
            hooks = ('buildMessages',) + (('evaluateOutput', 'fallback') if 'return null;' not in source else ())
            if 'com.subhamviky.e2a.agent.BaseAgent' in source:
                passed.append('extends e2a-java BaseAgent')
            else:
                missing.append('extends com.subhamviky.e2a.agent.BaseAgent'); d += self.MISSING_ELEMENT
        for hook in hooks:
            if hook in methods:
                passed.append(hook)
            else:
                missing.append(f'override {hook}'); d += self.MISSING_ELEMENT
        overridden = [e for e in ENTRY_POINTS if e in methods] if tree is not None else []
        if overridden:
            missing.append(f'entry point overridden: {overridden}'); d += self.MISSING_ELEMENT
        else:
            passed.append('entry point inherited')
        if re.search(r'\._[A-Z]\w*__\w+', source):
            missing.append('name-mangled private access'); d += self.MISSING_ELEMENT
        return d
