"""G2C for E2A v1.2 (A2C v1.2, wave C design note C-01: G-1, G-2, G-3, A-8).

The request may declare several agents, the workflow that runs them, the governance stages
and, per agent, what it reads, what it writes and the shape of its model output:

    "harness": {
      "e2a_contract": "1.2",
      "agents": [
        {"name": "RouterAgent", "kind": "model",
         "output_schema": {"type": "object", "required": ["intent"],
                           "properties": {"intent": {"enum": ["ORDER", "STATUS"]}}}},
        {"name": "OrderAgent", "kind": "deterministic", "reads": ["get_price"], "writes": ["submit_payment"]},
        {"name": "StatusAgent", "kind": "model", "reads": ["get_order"]}
      ],
      "workflow": {"name": "OrderWorkflow", "steps": [
        {"step": "route", "agent": "RouterAgent"},
        {"step": "act", "route_by": "intent", "agents": {"ORDER": "OrderAgent", "STATUS": "StatusAgent"},
         "material": true}]},
      "governance": {"stages": ["capacity", "token_budget", "firewall", "approval", "redaction"]}
    }

Generated (Python): one agent module per agent with the v1.2 hooks it needs (the
BOPF-style contract: each hook declares only what it uses), a Pydantic model per output
schema, the workflow as declared Steps, the governance stages and tool policy, the
validation service with one validator stub per agent, one tool stub per tool (material
for writes), and tests: AgentContract per agent, the conformance rules, and one request
through the workflow.
"""
import json
import re
from typing import Any, Dict, List, Optional

from a2c_contracts import Contract, python as contract_python

KINDS = ('model', 'deterministic')
STAGES = {        # name -> (expression, TODO comment)
    'capacity': ('CapacityStage(InflightLimiter(20))', ''),
    'token_budget': ('TokenBudgetStage()', ''),
    'firewall': ('FirewallStage(injection_patterns=[r"ignore (all )?(previous|prior) instructions"])',
                 'TODO: your patterns'),
    'approval': ('ApprovalStage(required=lambda state, ctx: False)', 'TODO: when a human must approve'),
    'sandbox': ('SandboxStage()', ''),
    'redaction': ('RedactionStage()', 'TODO: your redaction rules (compile_redactions)'),
}
STAGE_CLASSES = {'capacity': ['CapacityStage', 'InflightLimiter'], 'token_budget': ['TokenBudgetStage'],
                 'firewall': ['FirewallStage'], 'approval': ['ApprovalStage'], 'sandbox': ['SandboxStage'],
                 'redaction': ['RedactionStage']}


class HarnessError(ValueError):
    """The agents / workflow / governance declaration cannot be generated."""


def snake(name: str) -> str:
    s = re.sub(r'(?<=[a-z0-9])([A-Z])', r'_\1', name)
    return re.sub(r'[^a-zA-Z0-9]+', '_', s).strip('_').lower()


def pascal(name: str) -> str:
    return ''.join(p[:1].upper() + p[1:] for p in re.split(r'[^A-Za-z0-9]+', name) if p)


# ------------------------------------------------------------------ the request
def normalize(harness: Dict[str, Any]) -> Dict[str, Any]:
    """agents / workflow / governance, checked; a single agent_name becomes one model agent."""
    agents = harness.get('agents') or [{'name': harness.get('agent_name', 'GeneratedAgent')}]
    out, names = [], set()
    for raw in agents:
        a = {'name': raw} if isinstance(raw, str) else dict(raw)
        if not re.match(r'^[A-Z][A-Za-z0-9]*$', a.get('name', '')):
            raise HarnessError(f"agent name {a.get('name')!r}: use PascalCase")
        if a['name'] in names:
            raise HarnessError(f"agent {a['name']} is declared twice")
        names.add(a['name'])
        a.setdefault('kind', 'model')
        if a['kind'] not in KINDS:
            raise HarnessError(f"agent {a['name']}: kind must be one of {KINDS}")
        if a.get('output_schema') and a['kind'] != 'model':
            raise HarnessError(f"agent {a['name']}: output_schema needs kind 'model'")
        a['reads'], a['writes'] = list(a.get('reads') or []), list(a.get('writes') or [])
        out.append(a)
    workflow = harness.get('workflow')
    if workflow:
        workflow = dict(workflow)
        workflow.setdefault('name', 'GeneratedWorkflow')
        steps, step_names = [], set()
        for st in workflow.get('steps') or []:
            st = dict(st)
            if st.get('step') in step_names or not st.get('step'):
                raise HarnessError(f"workflow step {st.get('step')!r}: a unique name is required")
            step_names.add(st['step'])
            used = list((st.get('agents') or {}).values()) if 'route_by' in st else [st.get('agent')]
            unknown = [u for u in used if u not in names]
            if unknown:
                raise HarnessError(f"workflow step {st['step']}: unknown agent(s) {unknown}")
            steps.append(st)
        if not steps:
            raise HarnessError('workflow: at least one step')
        workflow['steps'] = steps
    stages = list((harness.get('governance') or {}).get('stages') or [])
    unknown = [s for s in stages if s not in STAGES]
    if unknown:
        raise HarnessError(f"governance: unknown stage(s) {unknown}; known: {sorted(STAGES)}")
    return {'agents': out, 'workflow': workflow, 'stages': stages}


def example(schema: Dict[str, Any]) -> Any:
    """A minimal valid instance of a (simple) JSON Schema, for the generated tests."""
    if 'const' in schema:
        return schema['const']
    if 'enum' in schema:
        return schema['enum'][0]
    t = schema.get('type')
    t = t[0] if isinstance(t, list) else t
    if t == 'object':
        return {k: example(v) for k, v in (schema.get('properties') or {}).items()
                if k in schema.get('required', [])}
    return {'string': 'x', 'integer': 1, 'number': 1.0, 'boolean': True, 'array': []}.get(t, 'x')


# ------------------------------------------------------------------ the agents
def output_model(agent: Dict[str, Any]) -> Optional[str]:
    schema = agent.get('output_schema')
    if not schema:
        return None
    return contract_python(Contract(f"{snake(agent['name'])}_output.json",
                                    dict(schema, **{'x-a2c-name': agent['name'] + 'Output'})))


def agent_source(agent: Dict[str, Any], package: str) -> str:
    name, kind = agent['name'], agent['kind']
    model = f"{name}Output" if agent.get('output_schema') else None
    head = [f'"""{name}: generated by G2C for E2A v1.2. Each hook declares only the parameters it uses',
            '(the BOPF-style contract: state, ctx, io_read, io_modify, messages, failed_keys).',
            'Fill the TODOs; the hooks you do not need keep the framework defaults."""']
    head += (['import json'] if kind == 'model' else []) + ['import logging', '', 'from e2a import BaseAgent']
    if model:
        head += ['from pydantic import ValidationError', '', f'from .{snake(name)}_output import {model}']
    lines = head
    lines += ['', '', f'class {name}(BaseAgent):', f"    agent_name = '{name}'", '']
    if agent['reads']:
        lines += ['    def _prepare(self, state, ctx, io_read):',
                  '        """Read the facts this agent needs (replay-safe reads; no side effects)."""']
        lines += [f"        state['{t}'] = io_read.call('{t}', {{}})  # TODO: the payload" for t in agent['reads']]
        lines.append('')
    if kind == 'model':
        lines += ['    def _build_messages(self, state, ctx):',
                  f"        return [{{'role': 'system', 'content': 'You are {name}. Answer as JSON.'}},  # TODO",
                  "                {'role': 'user', 'content': str(state.get('query', ''))}]", '',
                  '    def _evaluate_output(self, response, state, ctx):',
                  '        """Accept the model output only if it is valid; 0.0 sends the request to _fallback."""',
                  "        text = (response or {}).get('text', '') if isinstance(response, dict) else str(response or '')",
                  '        try:', '            data = json.loads(text)']
        if model:
            lines += [f'            state.update({model}.model_validate(data).model_dump(mode="json"))',
                      '        except (ValueError, ValidationError):']
        else:
            lines += [f"            state['{snake(name)}'] = data", '        except ValueError:']
        lines += ['            return 0.0', '        return 1.0', '',
                  '    def _fallback(self, state, ctx):',
                  "        return {'text': '', 'degraded': True}  # TODO: the safe answer", '']
    else:
        lines += ['    def _build_messages(self, state, ctx):',
                  '        return None                      # deterministic: no model step', '']
    if agent['writes']:
        lines += ['    def _act(self, state, ctx, io_modify):',
                  '        """Material effects, only after an accepted evaluation: every call carries the',
                  '        idempotency key and returns a typed outcome (COMMITTED / NOT_COMMITTED / UNKNOWN)."""',
                  '        return [']
        lines += [f"            io_modify.call('{t}', {{}}),  # TODO: the payload" for t in agent['writes']]
        lines += ['        ]', '']
    lines += ['    def _handle_error(self, error, state, ctx):',
              f"        logging.error(f'[{name}] {{error}}')",
              "        state.setdefault('errors', []).append(str(error))", '']
    return '\n'.join(lines)


# --------------------------------------------------------- workflow, governance, ...
def workflow_source(spec: Dict[str, Any], agents: List[Dict[str, Any]]) -> str:
    wf = spec['workflow']
    imports = '\n'.join(f"from ..agents.{snake(a['name'])} import {a['name']}" for a in agents)
    used_route = any('route_by' in s for s in wf['steps'])
    steps = []
    for s in wf['steps']:
        material = ', material=True' if s.get('material') else ''
        if 'route_by' in s:
            mapping = ', '.join(f"{k!r}: self.agents[{v!r}]" for k, v in s['agents'].items())
            steps.append(f"            Route({s['step']!r}, by={s['route_by']!r}, agents={{{mapping}}}{material}),")
        else:
            steps.append(f"            Step({s['step']!r}, self.agents[{s['agent']!r}]{material}),")
    names = ', '.join(f"{a['name']!r}: {a['name']}()" for a in agents)
    return f'''"""{wf['name']}: the request's steps, generated by G2C for E2A v1.2 (declared steps under one
idempotency claim, taken before the first material step; a paused step resumes with resume())."""
import logging

from e2a import BaseWorkflow, {"Route, " if used_route else ""}Step, Steps

{imports}


class {wf['name']}(BaseWorkflow):
    def __init__(self, agents=None) -> None:
        self.agents = agents or {{{names}}}

    def _build_workflow(self, ctx):
        return Steps(
{chr(10).join(steps)}
        )

    def _generate_idempotency_key(self, state, ctx) -> str:
        raise NotImplementedError("decide what makes two requests the same request")  # TODO

    def _requires_idempotency_claim(self, state, ctx) -> bool:
        return True  # TODO: False for requests without a material effect

    def _handle_error(self, error, state, ctx):
        logging.error(f"[{wf['name']}] {{error}}")
        state["status"] = "FAILED"
        state.setdefault("errors", []).append(str(error))
'''


def governance_source(spec: Dict[str, Any]) -> str:
    classes = sorted({c for s in spec['stages'] for c in STAGE_CLASSES[s]})
    policy = {a['name']: a['reads'] + a['writes'] for a in spec['agents']}
    stages = '\n'.join(f'        {STAGES[s][0]},' + (f'  # {STAGES[s][1]}' if STAGES[s][1] else '')
                       for s in spec['stages'])
    return f'''"""Governance for the agents (generated by G2C for E2A v1.2): ordered stages run for every
agent (screening before it reads, approval after), and each agent's tool allow-list."""
from e2a import BaseGovernanceFramework{"".join(", " + c for c in classes)}


class ServiceGovernance(BaseGovernanceFramework):
    tool_policy = {json.dumps(policy, indent=4).replace(chr(10), chr(10) + "    ")}

    def __init__(self) -> None:
        self.stages = [
{stages}
        ]
'''


def validation_source(spec: Dict[str, Any]) -> str:
    registry = '\n'.join(f"            {a['name']!r}: self._validate_{snake(a['name'])}," for a in spec['agents'])
    stubs = '\n'.join(f'''    def _validate_{snake(a['name'])}(self, state, config=None, **kwargs):
        return True, []  # TODO: the input {a['name']} requires
''' for a in spec['agents'])
    return f'''"""Input validation before any agent runs (generated by G2C): one validator per agent."""
from e2a import BaseValidationService, ValidationResult


class ServiceValidation(BaseValidationService):
    def __init__(self) -> None:
        self.validator_registry = {{
{registry}
        }}

{stubs}
    def _enforce_entitlement_gate(self, agent_name, state, config=None, **kwargs) -> ValidationResult:
        return ValidationResult(valid=True, errors=[], agent_name=agent_name)  # TODO: who may use which agent
'''


def tools_source(spec: Dict[str, Any]) -> str:
    material = {t for a in spec['agents'] for t in a['writes']}
    tools = sorted({t for a in spec['agents'] for t in a['reads'] + a['writes']})
    classes = '\n\n'.join(f'''class {pascal(t)}(BaseToolService):
    """{t}: {"a material effect (called through io_modify, always with an idempotency key)" if t in material
            else "a read (called through io_read, retried freely)"}."""
    material = {t in material}

    def _get_endpoint(self, config=None, tenant_id=None, **kwargs):
        return "local://{t}"  # TODO

    def _build_payload(self, payload, config=None, **kwargs):
        return payload

    def _validate_input(self, payload, config=None, **kwargs):
        return True  # TODO

    async def _send_request(self, endpoint, body, token=None, timeout=None, config=None, **kwargs):
        raise NotImplementedError("{t}: call the real system here")  # TODO
''' for t in tools)
    registry = ', '.join(f'{t!r}: {pascal(t)}()' for t in tools)
    return f'''"""The tools the agents use (generated by G2C): stubs to fill. config["tools"] = tools()."""
from e2a import BaseToolService


{classes}

def tools() -> dict:
    return {{{registry}}}
''' if tools else '"""No tools declared."""\n\n\ndef tools() -> dict:\n    return {}\n'


def tests(spec: Dict[str, Any], package: str) -> Dict[str, str]:
    out = {}
    contract_cases = '\n\n'.join(f'''class Test{a['name']}Contract(AgentContract):
    valid_state = {{"tenant_id": "test-tenant", "query": "test"}}

    def make_agent(self):
        return {a['name']}()
''' for a in spec['agents'])
    imports = '\n'.join(f"from {package}.agents.{snake(a['name'])} import {a['name']}" for a in spec['agents'])
    out['tests/test_agents_contract.py'] = f'''"""Generated by G2C: the behaviour every E2A agent keeps (e2a.conformance.AgentContract)."""
from e2a.conformance import AgentContract

{imports}


{contract_cases}'''
    out['tests/test_conformance.py'] = '''"""Generated by G2C: the Governed Entry Point rules over src/ (strict)."""
from pathlib import Path

from e2a.conformance import check_paths, failed


def test_governed_entry_points():
    findings = check_paths([str(Path(__file__).resolve().parents[1] / "src")])
    assert not failed(findings, strict=True), [str(f) for f in findings]
'''
    wf = spec.get('workflow')
    if wf:
        rules = []
        for a in spec['agents']:
            if a['kind'] == 'model':
                answer = json.dumps(example(a['output_schema'])) if a.get('output_schema') else '{}'
                rules.append(f'    llm.add_rule({a["name"]!r}, system_contains("You are {a["name"]}."), {answer!r})')
        first = wf['steps'][0]['step']
        out['tests/test_workflow.py'] = f'''"""Generated by G2C: one request through the declared steps, with the simulated model."""
from e2a_simulated_llm import SimulatedLLMService, system_contains

from {package}.tools.catalog import tools
from {package}.workflow.{snake(wf['name'])} import {wf['name']}


def test_one_request_runs_the_declared_steps():
    llm = SimulatedLLMService()
{chr(10).join(rules) if rules else "    pass"}
    state = {wf['name']}().execute({{"tenant_id": "test-tenant", "query": "test"}},
                                     {{"llm_service": llm, "tools": tools()}}, idempotency_key="test-1")
    assert state["steps"][0]["step"] == {first!r}
    assert all(s["status"] in ("DONE", "SKIPPED", "FALLBACK") for s in state["steps"]), state["steps"]
'''
    return out


def files(harness: Dict[str, Any], package: str) -> Dict[str, str]:
    """Every file G2C writes for a v1.2 Python harness, relative to the project root."""
    spec = normalize(harness)
    base = f'src/{package}'
    out = {f'{base}/agents/__init__.py': '"""The agents (generated by G2C for E2A v1.2)."""\n'}
    for a in spec['agents']:
        out[f"{base}/agents/{snake(a['name'])}.py"] = agent_source(a, package)
        model = output_model(a)
        if model:
            out[f"{base}/agents/{snake(a['name'])}_output.py"] = model
    if spec['workflow']:
        out[f'{base}/workflow/__init__.py'] = '"""The workflow (generated by G2C)."""\n'
        out[f"{base}/workflow/{snake(spec['workflow']['name'])}.py"] = workflow_source(spec, spec['agents'])
    if spec['stages']:
        out[f'{base}/services/governance.py'] = governance_source(spec)
    out[f'{base}/services/validation.py'] = validation_source(spec)
    out[f'{base}/tools/catalog.py'] = tools_source(spec)
    out.update(tests(spec, package))
    return out
