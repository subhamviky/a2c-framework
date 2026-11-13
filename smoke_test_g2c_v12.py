"""A2C v1.2 (wave C note C-01): G2C generates E2A v1.2 code, several agents at once.

G-1 agents + workflow + governance from one request · G-2 hooks from the declaration ·
G-3 the BOPF-style v1.2 contract · A-4 no application-service module · X-2 one request
through the generated workflow."""
import importlib
import json
import sys
import tempfile
from pathlib import Path

import g2c_v12
from a2c_cli import E2A_REF, build
from e2a.conformance import check_paths, failed

passed = 0
HERE = Path(__file__).resolve().parent


def check(name, ok):
    global passed
    print(('PASS ' if ok else 'FAIL ') + name)
    if not ok:
        sys.exit(1)
    passed += 1


def refused(fn, text):
    try:
        fn()
    except ValueError as e:
        return text in str(e)
    return False


check('G-1 an unknown kind is refused', refused(lambda: g2c_v12.normalize({'agents': [{'name': 'A', 'kind': 'x'}]}),
                                                'kind must be'))
check('G-1 a workflow step naming an unknown agent is refused', refused(lambda: g2c_v12.normalize(
    {'agents': ['A'], 'workflow': {'steps': [{'step': 's', 'agent': 'B'}]}}), 'unknown agent'))
check('G-1 an unknown governance stage is refused',
      refused(lambda: g2c_v12.normalize({'agents': ['A'], 'governance': {'stages': ['magic']}}), 'unknown stage'))
check('G-2 an output schema needs a model step', refused(lambda: g2c_v12.normalize(
    {'agents': [{'name': 'A', 'kind': 'deterministic', 'output_schema': {'type': 'object'}}]}), "needs kind 'model'"))

request = json.loads((HERE / 'examples/requests/agents-python.json').read_text())
with tempfile.TemporaryDirectory() as tmp:
    report = build(request, Path(tmp))
    root = Path(tmp) / 'agents-service'
    src = root / 'src' / 'agents_service'
    check('the build succeeds with the critic at 1.0', report['success'] and report['critic_score'] == 1.0)
    check('G-1 three agents, the workflow, governance, validation and tools are generated', all(
        (src / p).is_file() for p in ('agents/router_agent.py', 'agents/order_agent.py', 'agents/status_agent.py',
                                      'workflow/order_workflow.py', 'services/governance.py',
                                      'services/validation.py', 'tools/catalog.py')))
    router, order = (src / 'agents/router_agent.py').read_text(), (src / 'agents/order_agent.py').read_text()
    check('G-3 hooks declare the v1.2 parameters', 'def _build_messages(self, state, ctx):' in router
          and 'def _prepare(self, state, ctx, io_read):' in order and 'def _act(self, state, ctx, io_modify):' in order)
    check('G-2 a deterministic agent has no model step; writes go through io_modify',
          'return None' in order and "io_modify.call('submit_payment'" in order and '_evaluate_output' not in order)
    check('G-2 the output schema becomes a model the evaluation validates',
          'RouterAgentOutput.model_validate' in router and (src / 'agents/router_agent_output.py').is_file())
    check('G-2 material tools are flagged', 'material = True' in (src / 'tools/catalog.py').read_text())
    check('the generated project depends on E2A v1.2 (its code and tests import e2a)',
          f'e2a-framework.git", tag = "{E2A_REF}"' in (root / 'pyproject.toml').read_text())
    check('A-4 no application-service module', not (src / 'generated/service.py').exists()
          and (src / 'generated/nfr.py').exists())
    check('A-8 contract, conformance and workflow tests are generated',
          all((root / 'tests' / t).is_file() for t in ('test_agents_contract.py', 'test_conformance.py',
                                                         'test_workflow.py')))
    check('the generated code passes the Governed Entry Point rules (strict)',
          not failed(check_paths([str(root / 'src')]), strict=True))

    # X-2: one request through the generated workflow, in process
    sys.path.insert(0, str(root / 'src'))
    from e2a_simulated_llm import SimulatedLLMService, system_contains
    wf_module = importlib.import_module('agents_service.workflow.order_workflow')
    tools = importlib.import_module('agents_service.tools.catalog').tools()
    llm = SimulatedLLMService().add_rule('router', system_contains('You are RouterAgent.'), '{"intent": "STATUS"}')
    llm.add_rule('status', system_contains('You are StatusAgent.'), '{"status": "PAID"}')
    state = wf_module.OrderWorkflow().execute({'tenant_id': 't1', 'query': 'status of my order?'},
                                              {'llm_service': llm, 'tools': tools}, idempotency_key='k-1')
    check('X-2 the router chose the route and the routed agent ran',
          state['intent'] == 'STATUS' and [s['step'] for s in state['steps']] == ['route', 'act']
          and state['steps'][1]['agent'] == 'StatusAgent')

java = json.loads((HERE / 'examples/requests/java-azure-service.json').read_text())
java['harness'].update(e2a_contract='1.2', governance={'stages': ['redaction']})
check('D-01 Java on contract 1.2 is accepted (e2a-java), but only with the stages e2a-java has',
      refused(lambda: build(java, Path(tempfile.mkdtemp())), 'available for Java'))

single = json.loads((HERE / 'examples/requests/python-gcp-service.json').read_text())
with tempfile.TemporaryDirectory() as tmp:
    build(single, Path(tmp))
    agent = (Path(tmp) / 'image-py-service/src/image_py_service/agents/image_agent.py').read_text()
    check('G-3 a single-agent Python request gets a v1.2 agent by default',
          'from e2a import BaseAgent' in agent and 'def _build_messages(self, state, ctx):' in agent)

print(f'{passed} checks passed')
