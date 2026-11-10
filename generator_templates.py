"""generator_templates.py — deterministic skeletons for G2C TEMPLATE mode.

When no config['llm_service'] is bound, a generator emits these instead of a
model completion. Each passes GeneratorCriticAgent for its generator type, so
template mode exercises the full generate() sequence offline (CI, tests,
air-gapped scaffolding). They are skeletons, not the reference
implementation: the reference E2A scaffold is e2a-framework/reference/e2a_base.py
and the reference A2C classes are a2c_base.py in this repository.
"""
from pathlib import Path

ABSTRACT_FILES = {
    'e2a_abstract': {'python': 'e2a_base.py', 'java': 'E2ABase.java', 'node': 'e2aBase.ts', 'go': 'e2a_base.go'},
    'a2c_abstract': {'python': 'a2c_base.py', 'java': 'A2CBase.java', 'node': 'a2cBase.ts', 'go': 'a2c_base.go'},
}

_E2A_ENTRY = [('BaseAgent', 'run', 'state', ['_build_messages', '_apply_policy', '_evaluate_output',
                                              '_fallback', '_handle_error']),
              ('BaseWorkflow', 'execute', 'state', ['_build_workflow', '_validate_workflow', '_get_agent',
                                                   '_generate_idempotency_key', '_handle_error']),
              ('BaseRAGPipeline', 'retrieve', 'query', ['_search_index', '_rerank', '_evaluate_answer']),
              ('BaseToolService', 'execute', 'payload', ['get_endpoint', '_build_payload', '_validate_input'])]
_E2A_INTERFACES = ['BaseInfraProvisioner', 'BaseObservability', 'BasePipeline', 'BaseGovernanceFramework']


def snake(name: str) -> str:
    out = ''
    for i, ch in enumerate(name):
        if ch.isupper() and i and (not name[i - 1].isupper() or (i + 1 < len(name) and name[i + 1].islower())):
            out += '_'
        out += ch.lower()
    return out


def java_hook(name: str) -> str:
    """Java name of an E2A hook: '_build_messages' -> 'buildMessages'."""
    head, *rest = name.lstrip('_').split('_')
    return head + ''.join(w.capitalize() for w in rest)


def java_hooks(kind: str):
    """Hooks a Java inherited class must implement for its base."""
    hooks = [java_hook(h) for h in _E2A_ENTRY[0][3]]
    return [h for h in hooks if h != 'applyPolicy'] if kind == 'a2c_inherited' else hooks


# ───────────────────────────────────────────────────────────── E2A abstract
def e2a_abstract(runtime: str, package: str = 'com.company.common') -> str:
    if runtime == 'java':
        return _e2a_java(package)
    return {'python': _e2a_py, 'node': _e2a_ts, 'go': _e2a_go}[runtime]()


def _e2a_py() -> str:
    parts = ['"""E2A base abstract classes — G2C template skeleton.',
             'Reference implementation: e2a-framework/reference/e2a_base.py."""',
             'import time', 'import uuid', 'from abc import ABC, abstractmethod',
             'from typing import Any, Dict, List, Optional', '', '',
             'class NFRViolationError(Exception):', '    """Latency, token or governance limit breached."""', '', '',
             'class BaseLLMAgentService(ABC):',
             '    """The only place a model is called: permit, then quota, then call."""',
             '    async def process_inference(self, messages, config=None, **kwargs) -> Dict[str, Any]:',
             '        return await self._dispatch_upstream_call(messages, config, **kwargs)', '',
             '    async def process_inference_stream(self, messages, config=None, **kwargs):',
             '        async for chunk in self._dispatch_upstream_stream(messages, config, **kwargs):',
             '            yield chunk', '',
             '    @abstractmethod', '    async def _dispatch_upstream_call(self, messages, config=None, **kwargs): ...', '',
             '    @abstractmethod', '    def _dispatch_upstream_stream(self, messages, config=None, **kwargs): ...', '', '']
    for cls, entry, arg, hooks in _E2A_ENTRY:
        parts += [f'class {cls}(ABC):', f'    idempotency = True', f'    async_mode = True', '',
                  f'    def {entry}(self, {arg}, config: Dict[str, Any] = None, **kwargs):',
                  f'        """Single public entry point. Never override."""',
                  '        config = config or {}', '        start = time.time()',
                  '        key = self.__ensure_idempotency(config, **kwargs)']
        parts += [f'        self.{h}({arg}, config, idempotency_key=key, **kwargs)' for h in hooks[:2]]
        parts += ["        if (time.time() - start) > float(config.get('max_latency', 30.0)):",
                  "            raise NFRViolationError('latency SLO breached')",
                  f'        return {arg}', '']
        for h in hooks:
            parts += ['    @abstractmethod', f'    def {h}(self, *args, **kwargs): ...', '']
        parts += ['    def __ensure_idempotency(self, config, **kwargs) -> str:',
                  "        return kwargs.get('idempotency_key') or str(uuid.uuid4())", '', '']
    for iface in _E2A_INTERFACES:
        parts += [f'class {iface}(ABC):', '    """Foundation interface — no shared implementation."""',
                  '    @abstractmethod', '    def apply(self, *args, **kwargs): ...', '', '']
    return '\n'.join(parts).rstrip() + '\n'


def _e2a_java(package: str = 'com.company.common') -> str:
    body = []
    for cls, entry, arg, hooks in _E2A_ENTRY:
        names = [java_hook(h) for h in hooks]
        hk = '\n'.join(f'        protected abstract Object {h}(Map<String, Object> {arg}, Map<String, Object> config);'
                       for h in names)
        on_error = (f'                {names[-1]}({arg}, config);\n' if names[-1] == 'handleError'
                    else f'                throw e;\n')
        body.append(f'''    public abstract static class {cls} {{
        /** Single public entry point (template method). Never override. */
        public final Map<String, Object> {entry}(Map<String, Object> {arg}, Map<String, Object> config) {{
            Map<String, Object> cfg = config == null ? new HashMap<>() : config;
            long start = System.nanoTime();
            {arg}.putIfAbsent("idempotency_key", UUID.randomUUID().toString());
            try {{
                {names[0]}({arg}, cfg);
                {names[1]}({arg}, cfg);
            }} catch (RuntimeException e) {{
                {arg}.put("error", e.getMessage());
{on_error}            }}
            double maxSeconds = ((Number) cfg.getOrDefault("max_latency", 30.0)).doubleValue();
            if ((System.nanoTime() - start) / 1e9 > maxSeconds) {{
                throw new NFRViolationError("latency SLO breached");
            }}
            return {arg};
        }}
{hk}
    }}''')
    body.append('''    public abstract static class BaseLLMAgentService {
        public final Map<String, Object> processInference(List<Map<String, Object>> messages, Map<String, Object> config) {
            return dispatchUpstreamCall(messages, config);
        }
        public final Iterator<String> processInferenceStream(List<Map<String, Object>> messages, Map<String, Object> config) {
            return dispatchUpstreamStream(messages, config);
        }
        protected abstract Map<String, Object> dispatchUpstreamCall(List<Map<String, Object>> messages, Map<String, Object> config);
        protected abstract Iterator<String> dispatchUpstreamStream(List<Map<String, Object>> messages, Map<String, Object> config);
    }''')
    body.append('''    public static class NFRViolationError extends RuntimeException {
        public NFRViolationError(String message) { super(message); }
    }''')
    for iface in _E2A_INTERFACES:
        body.append(f'    public interface {iface} {{ void apply(Map<String, Object> state, Map<String, Object> config); }}')
    return (f'package {package};\n\nimport java.util.*;\n\n'
            '/** E2A base abstract classes — G2C template skeleton. */\n'
            'public final class E2ABase {\n    private E2ABase() {}\n\n' + '\n\n'.join(body) + '\n}\n')


def _e2a_ts() -> str:
    out = ['// E2A base abstract classes — G2C template skeleton.']
    for cls, entry, arg, hooks in _E2A_ENTRY:
        out.append(f'export abstract class {cls} {{\n  {entry}({arg}: Record<string, unknown>, config: Record<string, unknown> = {{}}) {{\n    return {arg};\n  }}\n'
                   + '\n'.join(f'  protected abstract {h}(...args: unknown[]): unknown;' for h in hooks) + '\n}')
    out.append('export abstract class BaseLLMAgentService {\n  async processInference(messages: unknown[], config = {}) { return this.dispatchUpstreamCall(messages, config); }\n'
               '  async *processInferenceStream(messages: unknown[], config = {}) { yield* this.dispatchUpstreamStream(messages, config); }\n'
               '  protected abstract dispatchUpstreamCall(messages: unknown[], config: unknown): Promise<unknown>;\n'
               '  protected abstract dispatchUpstreamStream(messages: unknown[], config: unknown): AsyncIterable<string>;\n}')
    out += [f'export interface {i} {{ apply(state: unknown, config: unknown): void; }}' for i in _E2A_INTERFACES]
    return '\n\n'.join(out) + '\n'


def _e2a_go() -> str:
    out = ['// Package e2a — E2A base contracts, G2C template skeleton.', 'package e2a']
    for cls, entry, arg, hooks in _E2A_ENTRY + [('BaseLLMAgentService', 'ProcessInference', 'messages',
                                                ['ProcessInferenceStream'])]:
        out.append(f'type {cls} interface {{\n\t{entry[0].upper() + entry[1:]}({arg} map[string]any, config map[string]any) (map[string]any, error)\n'
                   + '\n'.join(f'\t{h.lstrip("_")}(args ...any) any' for h in hooks) + '\n}')
    out += [f'type {i} interface {{\n\tApply(state map[string]any, config map[string]any)\n}}' for i in _E2A_INTERFACES]
    return '\n\n'.join(out) + '\n'


# ───────────────────────────────────────────────────────────── A2C abstract
def a2c_abstract(runtime: str, package: str = 'com.company.common') -> str:
    if runtime == 'python':
        ref = Path(__file__).resolve().parent / 'a2c_base.py'
        if ref.exists():
            return ref.read_text(encoding='utf-8')
    names = ['DevRequest', 'SDLCAssistantAgent', 'CodeCriticAgent', 'SDLCWorkflow']
    if runtime == 'java':
        return (f'package {package};\n\nimport java.util.*;\n\n/** A2C base classes — G2C template skeleton. */\n'
                'public final class A2CBase {\n    private A2CBase() {}\n'
                '    public static final List<String> MANDATORY_NFRS = List.of("Idempotency", "Observability", "CircuitBreaker", '
                '"RetryWithBackoff", "HealthCheck", "GracefulShutdown");\n'
                '    public static class DevRequest extends HashMap<String, Object> {}\n'
                '    public abstract static class SDLCAssistantAgent extends E2ABase.BaseAgent {\n'
                '        protected Object applyPolicy(Map<String, Object> state, Map<String, Object> config) { return state; }\n    }\n'
                '    public abstract static class CodeCriticAgent extends E2ABase.BaseAgent {}\n'
                '    public abstract static class SDLCWorkflow extends E2ABase.BaseWorkflow {}\n}\n')
    if runtime == 'node':
        return ("import { BaseAgent, BaseWorkflow } from './e2aBase';\n\n"
                "export const MANDATORY_NFRS = ['Idempotency', 'Observability', 'CircuitBreaker', 'RetryWithBackoff', 'HealthCheck', 'GracefulShutdown'];\n"
                'export interface DevRequest { project_name: string; project_type: string; mandatory_nfrs: string[]; target_cloud: string; }\n'
                'export abstract class SDLCAssistantAgent extends BaseAgent {\n  protected _apply_policy(state: DevRequest) { return state; }\n}\n'
                'export abstract class CodeCriticAgent extends BaseAgent {}\nexport abstract class SDLCWorkflow extends BaseWorkflow {}\n')
    return ('package a2c\n\nvar MANDATORY_NFRS = []string{"Idempotency", "Observability", "CircuitBreaker", "RetryWithBackoff", "HealthCheck", "GracefulShutdown"}\n\n'
            'type DevRequest struct {\n\tProjectName string\n\tProjectType string\n\tMandatoryNFRs []string\n\tTargetCloud string\n}\n\n'
            + '\n'.join(f'type {n} interface {{\n\t_apply_policy(state map[string]any) error\n}}\n' for n in names[1:]))


# ─────────────────────────────────────────────────────────────── inherited
def inherited(kind: str, runtime: str, agent: str, import_line: str, nfrs=None,
              package: str = None) -> str:
    base = 'SDLCAssistantAgent' if kind == 'a2c_inherited' else 'BaseAgent'
    nfrs = list(nfrs or [])
    if runtime == 'python':
        policy = ('        super()._apply_policy(state, config, **kwargs)\n'
                  f'        for nfr in {nfrs!r}:\n'
                  "            if nfr not in state.setdefault('mandatory_nfrs', []):\n"
                  "                state['mandatory_nfrs'].append(nfr)\n") if kind == 'a2c_inherited' else (
                  "        approved = (config or {}).get('approved_agents')\n"
                  '        if approved is not None and self.agent_name not in approved:\n'
                  "            raise PermissionError(f'{self.agent_name} is not an approved agent')\n")
        return f'''"""{agent} — generated by G2C ({kind}). Template skeleton: fill the hooks."""
import logging

{import_line}


class {agent}({base}):
    """Inherits the public entry point and every NFR from {base}.
    Input validation is a _validate_{snake(agent)} validator on the
    BaseValidationService subclass; the model is reached only through
    config['llm_service']."""
    agent_name = '{agent}'

    def _build_messages(self, state, config=None, **kwargs) -> list:
        return [{{'role': 'system', 'content': 'You are {agent}.'}},
                {{'role': 'user', 'content': str(state.get('context') or state.get('query', ''))}}]

    def _apply_policy(self, state, config=None, **kwargs) -> None:
{policy}
    def _evaluate_output(self, response, state, config=None, **kwargs) -> float:
        text = (response or {{}}).get('text', '') if isinstance(response, dict) else str(response or '')
        return 1.0 if text.strip() else 0.0

    def _fallback(self, state, config=None, **kwargs):
        return {{'text': '', 'degraded': True}}

    def _handle_error(self, error, state, config=None, **kwargs):
        logging.error(f'[{{self.agent_name}}] {{error}}')
        state.setdefault('errors', []).append(str(error))
        return state
'''
    if runtime == 'java':
        bodies = {
            'buildMessages': 'return List.of(Map.of("role", "system", "content", "You are " + AGENT_NAME + "."));',
            'applyPolicy': 'return state;',
            'evaluateOutput': 'return state.containsKey("error") ? 0.0 : 1.0;',
            'fallback': 'return Map.of("text", "", "degraded", true);',
            'handleError': 'state.computeIfAbsent("errors", k -> new ArrayList<Object>()); return state;',
        }
        methods = '\n\n'.join(
            f'    @Override\n    protected Object {h}(Map<String, Object> state, Map<String, Object> config) {{\n'
            f'        {bodies[h]}\n    }}' for h in java_hooks(kind))
        pkg = f'package {package};\n\n' if package else ''
        return f'''{pkg}{import_line}

import java.util.*;

/** {agent} — generated by G2C ({kind}). Template skeleton: fill the hooks. */
public class {agent} extends {base} {{
    public static final String AGENT_NAME = "{agent}";

{methods}
}}
'''
    if runtime == 'node':
        return f'''{import_line}

/** {agent} — generated by G2C ({kind}). */
export class {agent} extends {base} {{
  protected _build_messages(state: Record<string, unknown>) {{
    return [{{ role: 'system', content: 'You are {agent}.' }}];
  }}

  protected _evaluate_output(response: unknown) {{
    return response ? 1.0 : 0.0;
  }}
}}
'''
    return f'''package agents

{import_line}

// {agent} — generated by G2C ({kind}).
type {agent} struct {{
	{base}
}}

func (a *{agent}) _build_messages(state map[string]any) []map[string]string {{
	return []map[string]string{{{{"role": "system", "content": "You are {agent}."}}}}
}}

func (a *{agent}) _evaluate_output(response any) float64 {{
	return 1.0
}}
'''


def import_line(kind: str, runtime: str, source: str, package_name: str = None,
                java_common_package: str = None) -> str:
    base = 'SDLCAssistantAgent' if kind == 'a2c_inherited' else 'BaseAgent'
    mod = 'a2c_base' if kind == 'a2c_inherited' else 'e2a_base'
    if runtime == 'python':
        return f'from {package_name} import {base}' if source == 'package' and package_name \
            else f'from common.{mod} import {base}'
    if runtime == 'java':
        holder = 'A2CBase' if kind == 'a2c_inherited' else 'E2ABase'
        pkg = package_name if source == 'package' and package_name else (java_common_package or 'com.company.common')
        return f'import {pkg}.{holder}.{base};'
    if runtime == 'node':
        return f"import {{ {base} }} from '{package_name if source == 'package' and package_name else '../common/' + ('a2cBase' if kind == 'a2c_inherited' else 'e2aBase')}';"
    return f'import . "{package_name or "example.com/common/" + mod.split("_")[0]}"'
