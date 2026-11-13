"""G2C for Java on E2A v1.2 (A2C v1.2.1, wave D note D-01): agents, workflow, governance, tools
and contract tests generated against e2a-java (com.subhamviky.e2a), from the same declaration as
Python (harness.agents / workflow / governance, checked by g2c_v12.normalize).

Since A2C v1.3 this is the default for a Java e2a_inherited request ("1.1" was removed).
"""
import json
from typing import Any, Dict, List

import g2c_v12
from g2c_v12 import HarnessError, example, pascal

E2A_JAVA_VERSION = '1.3.0'
STAGES = {        # the stages e2a-java has -> (expression, TODO comment)
    'capacity': ('new CapacityStage(() -> true)', 'TODO: admit only while the service has capacity'),
    'firewall': ('new FirewallStage(List.of("ignore (all )?(previous|prior) instructions"), 4000, List.of("text"))',
                 'TODO: your patterns and the fields to screen'),
    'approval': ('new ApprovalStage((state, ctx) -> false)', 'TODO: when a human must approve'),
}


def normalize(harness: Dict[str, Any]) -> Dict[str, Any]:
    spec = g2c_v12.normalize(harness)
    unsupported = [s for s in spec['stages'] if s not in STAGES]
    if unsupported:
        raise HarnessError(f'governance: stage(s) {unsupported} are not in e2a-java {E2A_JAVA_VERSION}; '
                           f'available for Java: {sorted(STAGES)}')
    return spec


def _path(package: str) -> str:
    return package.replace('.', '/')


def _str(value: Any) -> str:
    return json.dumps(value)            # a Java string literal for simple text


# ------------------------------------------------------------------ the agents
def agent_source(agent: Dict[str, Any], package: str) -> str:
    name, model = agent['name'], agent['kind'] == 'model'
    pkg = f'{package}.agents' if package else 'agents'
    imports = {'com.subhamviky.e2a.agent.BaseAgent', 'com.subhamviky.e2a.core.RequestContext',
               'java.util.List', 'java.util.Map'}
    body: List[str] = []
    if agent['reads']:
        imports.add('com.subhamviky.e2a.tool.ReadAccess')
        calls = '\n'.join(f'        state.put("{r}", io.call("{r}", Map.of()).body());   // TODO: the payload'
                          for r in agent['reads'])
        body.append(f'''    /** Reads before the prompt, through io_read only: {", ".join(agent["reads"])}. */
    @Override
    protected void prepare(Map<String, Object> state, RequestContext ctx, ReadAccess io) {{
{calls}
    }}
''')
    if model:
        body.append(f'''    @Override
    protected List<Map<String, String>> buildMessages(Map<String, Object> state, RequestContext ctx) {{
        return List.of(Map.of("role", "system", "content", "You are {name}."),       // TODO: the prompt
                Map.of("role", "user", "content", String.valueOf(state.get("text"))));
    }}
''')
        schema = agent.get('output_schema') or {}
        required = list(schema.get('required') or [])
        enums = {k: v['enum'] for k, v in (schema.get('properties') or {}).items() if isinstance(v, dict) and 'enum' in v}
        imports.update({'com.fasterxml.jackson.databind.ObjectMapper', 'com.subhamviky.e2a.llm.LlmResponse'})
        checks = ''.join(f'''        if (!answer.containsKey("{k}")) {{
            return 0.0;
        }}
''' for k in required) + ''.join(f'''        if (!List.of({", ".join(_str(x) for x in v)}).contains(String.valueOf(answer.get("{k}")))) {{
            return 0.0;
        }}
''' for k, v in enums.items())
        body.append(f'''    private static final ObjectMapper JSON = new ObjectMapper();

    /** The answer must be JSON{" with " + ", ".join(required) if required else ""}; anything else falls back. */
    @Override
    protected double evaluateOutput(LlmResponse response, Map<String, Object> state, RequestContext ctx) {{
        Map<?, ?> answer;
        try {{
            answer = JSON.readValue(response.text(), Map.class);
        }} catch (Exception notJson) {{
            return 0.0;
        }}
{checks}        state.putAll((Map<String, Object>) answer);
        return 1.0;
    }}

    @Override
    protected Object fallback(Map<String, Object> state, RequestContext ctx) {{
        return "{name} could not answer; a person will follow up";      // TODO: the degraded answer
    }}
''')
    else:
        body.append('''    /** A deterministic agent: no model step. */
    @Override
    protected List<Map<String, String>> buildMessages(Map<String, Object> state, RequestContext ctx) {
        return null;
    }
''')
    if agent['writes']:
        imports.update({'com.subhamviky.e2a.tool.ModifyAccess', 'com.subhamviky.e2a.tool.ToolResult'})
        calls = ',\n'.join(f'                io.call("{w}", Map.of())' for w in agent['writes'])
        body.append(f'''    /** Material effects, through io_modify only (always with an idempotency key). */
    @Override
    protected List<ToolResult> act(Map<String, Object> state, RequestContext ctx, ModifyAccess io) {{
        // TODO: the payload of each call
        return List.of(
{calls});
    }}
''')
    suppress = '@SuppressWarnings("unchecked")\n' if model else ''
    return (f'package {pkg};\n\n' + ''.join(f'import {i};\n' for i in sorted(imports)) + f'''
/**
 * {name} — generated by G2C for E2A v1.2 (e2a-java {E2A_JAVA_VERSION}) from its declaration:
 * kind {agent["kind"]}{", reads " + ", ".join(agent["reads"]) if agent["reads"] else ""}{", writes " + ", ".join(agent["writes"]) if agent["writes"] else ""}.
 * run() is inherited and final; fill in the TODOs.
 */
{suppress}public class {name} extends BaseAgent {{

''' + '\n'.join(body) + '}\n')


def workflow_source(spec: Dict[str, Any], package: str) -> str:
    wf = spec['workflow']
    steps = []
    for st in wf['steps']:
        if 'route_by' in st:
            agents = ', '.join(f'"{k}", new {v}()' for k, v in st['agents'].items())
            s = f'Route.by("{st["step"]}", "{st["route_by"]}", Map.of({agents}))'
        else:
            s = f'Step.of("{st["step"]}", new {st["agent"]}())'
        steps.append(s + ('.materialStep()' if st.get('material') else ''))
    imports = sorted({f'{package}.agents.{a["name"]}' for a in spec['agents']} | {
        'com.subhamviky.e2a.core.RequestContext', 'com.subhamviky.e2a.workflow.BaseWorkflow',
        'com.subhamviky.e2a.workflow.Steps', 'java.util.Map'} | (
        {'com.subhamviky.e2a.workflow.Route'} if any('route_by' in s for s in wf['steps']) else set()) | (
        {'com.subhamviky.e2a.workflow.Step'} if any('route_by' not in s for s in wf['steps']) else set()))
    joined = ',\n                '.join(steps)
    return (f'package {package}.workflow;\n\n' + ''.join(f'import {i};\n' for i in imports) + f'''
/** {wf["name"]} — the declared steps (e2a-java). execute() is inherited and final. */
public class {wf["name"]} extends BaseWorkflow {{

    @Override
    protected Steps buildWorkflow(RequestContext ctx) {{
        return Steps.of(
                {joined});
    }}

    @Override
    protected String generateIdempotencyKey(Map<String, Object> state, RequestContext ctx) {{
        throw new UnsupportedOperationException("decide what makes two requests the same");   // TODO
    }}
}}
''')


def governance_source(spec: Dict[str, Any], package: str) -> str:
    stages = ',\n'.join((f'                // {STAGES[s][1]}\n' if STAGES[s][1] else '') + f'                {STAGES[s][0]}'
                        for s in spec['stages'])
    policy = ',\n'.join(f'                "{a["name"]}", Set.of({", ".join(_str(t) for t in a["reads"] + a["writes"])})'
                        for a in spec['agents'])
    classes = sorted({STAGES[s][0].split('(')[0].replace('new ', '') for s in spec['stages']})
    imports = sorted({'com.subhamviky.e2a.governance.Governance', 'java.util.List', 'java.util.Map', 'java.util.Set'}
                     | {f'com.subhamviky.e2a.governance.{c}' for c in classes})
    return (f'package {package}.governance;\n\n' + ''.join(f'import {i};\n' for i in imports) + f'''
/** The service's governance: ordered stages and each agent's tools (e2a-java). */
public final class ServiceGovernance {{

    private ServiceGovernance() {{
    }}

    public static Governance build() {{
        return new Governance(List.of(
{stages}),
            Map.of(
{policy}));
    }}
}}
''')


def tools_source(spec: Dict[str, Any], package: str) -> Dict[str, str]:
    out = {}
    for tool, material in sorted({t: False for a in spec['agents'] for t in a['reads']}.items()
                                 | {t: True for a in spec['agents'] for t in a['writes']}.items()):
        cls = pascal(tool) + 'Tool'
        flag = '''
    @Override
    public boolean material() {
        return true;
    }
''' if material else ''
        out[f'{_path(package)}/tools/{cls}.java'] = f'''package {package}.tools;

import com.subhamviky.e2a.core.RequestContext;
import com.subhamviky.e2a.tool.ToolService;

import java.util.Map;

/** {tool} — {"a material tool (reached only through io_modify)" if material else "a read (replay-safe)"}. TODO: connect it. */
public class {cls} implements ToolService {{
{flag}
    @Override
    public Map<String, Object> execute(Map<String, Object> payload, RequestContext ctx, String idempotencyKey) {{
        throw new UnsupportedOperationException("connect {tool}");
    }}
}}
'''
    return out


def tests(spec: Dict[str, Any], package: str) -> Dict[str, str]:
    """An AgentContract test per agent (fake tools, a simulated model answering the schema's example)."""
    tools = sorted({t for a in spec['agents'] for t in a['reads'] + a['writes']})
    material = {t for a in spec['agents'] for t in a['writes']}
    out = {}
    for a in spec['agents']:
        answer = json.dumps(example(a['output_schema'])) if a.get('output_schema') else '{}'
        fakes = ''.join(f'''
                .withTool("{t}", new ToolService() {{
                    {"public boolean material() { return true; }" if t in material else ""}
                    public Map<String, Object> execute(Map<String, Object> p, RequestContext c, String k) {{
                        return Map.of();
                    }}
                }})''' for t in tools)
        out[f'{_path(package)}/agents/{a["name"]}ContractTest.java'] = f'''package {package}.agents;

import com.subhamviky.e2a.E2AConfig;
import com.subhamviky.e2a.agent.BaseAgent;
import com.subhamviky.e2a.core.RequestContext;
import com.subhamviky.e2a.llm.SimulatedLlmService;
import com.subhamviky.e2a.test.AgentContract;
import com.subhamviky.e2a.tool.ToolService;

import java.util.Map;

/** The E2A agent guarantees for {a["name"]} (e2a-test AgentContract), with fake tools. */
class {a["name"]}ContractTest extends AgentContract {{

    @Override
    protected BaseAgent agent() {{
        return new {a["name"]}();
    }}

    @Override
    protected Map<String, Object> validState() {{
        return Map.of("text", "a request {a["name"]} handles");      // TODO: a realistic request
    }}

    @Override
    protected E2AConfig config() {{
        return E2AConfig.empty().withLlm(new SimulatedLlmService({json.dumps(answer)})){fakes};
    }}
}}
'''
    return out


def files(harness: Dict[str, Any], package: str) -> Dict[str, str]:
    """Every generated file except the primary agent's, keyed by path relative to the project."""
    spec = normalize(harness)
    main, test = f'src/main/java/{_path(package)}', 'src/test/java'
    out = {f'{main}/agents/{a["name"]}.java': agent_source(a, package) for a in spec['agents']}
    if spec['workflow']:
        out[f'{main}/workflow/{spec["workflow"]["name"]}.java'] = workflow_source(spec, package)
    out[f'{main}/governance/ServiceGovernance.java'] = governance_source(spec, package)
    out.update({f'src/main/java/{k}': v for k, v in tools_source(spec, package).items()})
    out.update({f'{test}/{k}': v for k, v in tests(spec, package).items()})
    return out
