"""Smoke tests for the G2C method contract (G2C Framework Reference §4–§11):
real file output, the structural critic, the abstract -> P0 -> inherited
chain, shared abstract classes, the factory, governance, JSON input and the
FastAPI router. Template mode and in-memory doubles only.
Run: python smoke_test_g2c_contract.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from a2c_concurrency import InMemoryClaimStore, Deadline
from base_generator_agent import BaseGeneratorAgent
from e2a_abstract_class_generator import E2AAbstractClassGenerator
from developer_platform_workflow import DeveloperPlatformWorkflow
from generator_factory import GeneratorFactory
from generator_critic_agent import GeneratorCriticAgent

ok = 0
def check(name, cond):
    global ok
    assert cond, name
    ok += 1
    print('PASS', name)

class BadLLM:
    """Gateway double that always returns structurally invalid code."""
    calls = 0
    async def process_inference(self, messages, **kw):
        BadLLM.calls += 1
        return {'status': 'SUCCESS', 'text': 'class Nothing:\n    pass\n'}

# ---- 1 template mode writes a real, critic-passing file for every runtime
for rt, fname in [('python', 'e2a_base.py'), ('java', 'E2ABase.java'), ('node', 'e2aBase.ts'), ('go', 'e2a_base.go')]:
    d = tempfile.mkdtemp()
    r = E2AAbstractClassGenerator().generate({'generator_type': 'e2a_abstract', 'runtime': rt, 'output_path': d}, {})
    f = r['generated_files'][0]
    check(f'{rt}: {fname} written and scored {r["critic_report"]["score"]}',
          r['success'] and f.endswith(fname) and os.path.getsize(f) > 200 and r['critic_report']['mode'] == 'template')

# ---- 2 a model reply that fails the critic is regenerated twice, then final; nothing written
d, store = tempfile.mkdtemp(), InMemoryClaimStore()
r = E2AAbstractClassGenerator().generate({'generator_type': 'e2a_abstract', 'runtime': 'python', 'output_path': d,
                                          'tenant_id': 't1'}, {'llm_service': BadLLM(), 'idempotency_store': store})
check('structural critic rejects bad output after 3 attempts', r['status'] == 'critic_threshold_not_met'
      and BadLLM.calls == 3 and 'BaseAgent' in r['critic_report']['missing'])
check('nothing written on critic failure', not os.listdir(d))

# ---- 3 inherited with scaffold: abstract -> P0 inline -> class in the scaffold
out = tempfile.mkdtemp()
wf = DeveloperPlatformWorkflow(config={})       # the constructor AI-DLC uses
req = {'generator_type': 'e2a_inherited', 'runtime': 'python', 'agent_name': 'RefundAgent',
       'output_path': out, 'platform': 'aws', 'tenant_id': 't1',
       'scaffold': {'project_name': 'Refunds', 'package_name': 'refunds'}}
cfg = {'a2c': {'enabled': True, 'project_type': 'FastAPI Microservice'}}
r = wf.generate(dict(req), cfg)
root = r['scaffold_result']['project_root']
cls = os.path.join(root, 'src', 'refunds', 'agents', 'refund_agent.py')
check('flat GeneratorResult with success and scaffold_result', r['success'] and r['status'] == 'generated' and r['scaffold_result']['success'])
check('P0 ran inline: manifest in the project', os.path.isfile(os.path.join(root, 'pyproject.toml')))
check('inherited class written inside the scaffold', cls in r['generated_files'] and os.path.isfile(cls))
check('base copied into the project common/', os.path.isfile(os.path.join(root, 'common', 'e2a_base.py')))
check('dev_request handed off for A2C', r['scaffold_result']['dev_request']['project_root'] == root
      and r['scaffold_result']['dev_request']['tenant_id'] == 't1')
check('abstract class generated fresh by this request', r['abstract_class_generated_fresh'] is True)
src = open(cls).read()
check('generated class extends BaseAgent and keeps run()', 'class RefundAgent(BaseAgent)' in src and 'def run(' not in src)

# ---- 4 a second project of the same tenant shares the abstract class
r2 = wf.generate({**req, 'agent_name': 'ChargeAgent', 'scaffold': {'project_name': 'Charges', 'package_name': 'charges'}}, cfg)
rec = wf.artifact_registry.get(r['abstract_class_path'])
check('second project reuses the shared base (not fresh)', r2['success'] and r2['abstract_class_generated_fresh'] is False
      and r2['abstract_class_path'] == r['abstract_class_path'])
check('shared base has two references, one creator', sorted(rec['refs']) == sorted([r['generator_key'], r2['generator_key']])
      and rec['creator'] == r['generator_key'])
check('shared base copied into the second project too',
      os.path.isfile(os.path.join(r2['scaffold_result']['project_root'], 'common', 'e2a_base.py')))
comp = wf.compensate(req, r)
check('creator compensating while another reference remains keeps the file', comp['removed'] is False and os.path.isfile(r['abstract_class_path']))

# ---- 5 a2c_inherited chain: E2A base, A2C base, SDLCAssistantAgent subclass
out5 = tempfile.mkdtemp()
r = DeveloperPlatformWorkflow().generate({'generator_type': 'a2c_inherited', 'runtime': 'python',
                                          'agent_name': 'TeamSDLCAgent', 'output_path': out5,
                                          'mandatory_nfrs': ['DoubleEntryLedger']}, {})
check('a2c chain records both bases', r['success'] and r['e2a_abstract_class_path'].endswith('e2a_base.py')
      and r['abstract_class_path'].endswith('a2c_base.py'))
src = open(r['generated_files'][-1]).read()
check('team agent extends SDLCAssistantAgent and adds its NFRs on top',
      'class TeamSDLCAgent(SDLCAssistantAgent)' in src and 'super()._apply_policy' in src and 'DoubleEntryLedger' in src)

# ---- 6 package source: no abstract generation, package import
out6 = tempfile.mkdtemp()
r = DeveloperPlatformWorkflow().generate({'generator_type': 'e2a_inherited', 'runtime': 'python', 'agent_name': 'PkgAgent',
                                          'output_path': out6, 'abstract_class_source': 'package',
                                          'package_name': 'e2a_framework'}, {})
check('package source imports from the package and generates no base',
      r['success'] and 'from e2a_framework import BaseAgent' in open(r['generated_files'][0]).read()
      and not os.path.exists(os.path.join(out6, 'common')))

# ---- 7 Java inherited class lands in the Maven tree
out7 = tempfile.mkdtemp()
r = DeveloperPlatformWorkflow().generate({'generator_type': 'e2a_inherited', 'runtime': 'java', 'agent_name': 'SettlementAgent',
                                          'output_path': out7, 'platform': 'aws',
                                          'scaffold': {'project_name': 'Settle', 'group_id': 'com.acme.settle',
                                                       'artifact_id': 'settle', 'project_type': 'spring_boot'}}, {})
check('Java class under src/main/java/<group>/service', r['success'] and
      r['generated_files'][-1].endswith('src/main/java/com/acme/settle/service/SettlementAgent.java'))
r = DeveloperPlatformWorkflow().generate({'generator_type': 'e2a_inherited', 'runtime': 'java', 'agent_name': 'NoType',
                                          'output_path': out7, 'scaffold': {'project_name': 'X', 'group_id': 'g', 'artifact_id': 'x'}}, {})
check('P0 failure (Java without project_type) is a typed scaffold_failed', r['status'] == 'scaffold_failed' and not r['success'])

# ---- 8 factory, governance, JSON input, deadline interop
g = GeneratorFactory.create({'generator_type': 'e2a_abstract'}, {'k': 1})
check('factory passes config to the generator', g.config == {'k': 1})
class ToolGen(E2AAbstractClassGenerator):
    generator_type = 'e2a_abstract'
GeneratorFactory.register('e2a_tool', ToolGen)
check('factory register() adds a type', isinstance(GeneratorFactory.create('e2a_tool'), ToolGen))
try:
    GeneratorFactory.create('nope'); check('unknown type rejected', False)
except ValueError:
    check('unknown type rejected', True)
try:
    E2AAbstractClassGenerator().generate({'generator_type': 'e2a_abstract', 'runtime': 'cobol', 'output_path': '.'}, {})
    check('unapproved runtime rejected', False)
except ValueError:
    check('unapproved runtime rejected', True)
try:
    E2AAbstractClassGenerator().generate({'generator_type': 'e2a_abstract', 'runtime': 'python', 'output_path': '.',
                                          'mandatory_nfrs': ['Telepathy']}, {'approved_nfrs': ['Idempotency']})
    check('NFR outside the allow-list rejected', False)
except PermissionError:
    check('NFR outside the allow-list rejected', True)
d8 = tempfile.mkdtemp(); cf = os.path.join(d8, 'generator-config.json')
json.dump({'generator': {'generator_type': 'e2a_abstract', 'runtime': 'go', 'output_path': d8}}, open(cf, 'w'))
r = E2AAbstractClassGenerator().generate({'source': 'json', 'config_path': cf}, {})
check('source=json resolves the generator section', r['success'] and r['generated_files'][0].endswith('e2a_base.go'))
check('Deadline is float-coercible for the E2A gateway', 0 < float(Deadline.after(5)) <= 5)

# ---- 8b replay never returns outputs that no longer exist
import shutil
from base_project_bootstrapper import PythonPoetryBootstrapper
st = InMemoryClaimStore(); d8b = tempfile.mkdtemp(); c8 = {'idempotency_store': st, 'output_path': d8b}
sreq = {'project_name': 'Gone', 'package_name': 'gone', 'runtime': 'python', 'build_tool': 'poetry', 'platform': 'aws', 'tenant_id': 't'}
first = PythonPoetryBootstrapper(c8).bootstrap(sreq, c8); shutil.rmtree(first['project_root'])
again = PythonPoetryBootstrapper(c8).bootstrap(sreq, c8)
check('P0 replay of a deleted workspace -> recovery_required', again['status'] == 'recovery_required' and not again['success'])
c8g = {'idempotency_store': InMemoryClaimStore()}
greq = {'generator_type': 'e2a_abstract', 'runtime': 'python', 'output_path': tempfile.mkdtemp(), 'tenant_id': 't'}
g1 = E2AAbstractClassGenerator().generate(greq, c8g); os.remove(g1['generated_files'][0])
g2 = E2AAbstractClassGenerator().generate(greq, c8g)
check('G2C replay of a deleted file -> recovery_required', g2['status'] == 'recovery_required' and not g2['success'])

# ---- 9 router
try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import generator_api_router as api
    app = FastAPI(); app.include_router(api.router); api.configure_generator({})
    c = TestClient(app); d9 = tempfile.mkdtemp()
    check('GET /health', c.get('/api/v1/g2c/health').json() == {'status': 'ok'})
    resp = c.post('/api/v1/g2c/e2a/abstract', json={'runtime': 'node', 'output_path': d9}).json()
    check('POST /e2a/abstract generates', resp['success'] and resp['generated_files'][0].endswith('e2aBase.ts'))
    resp = c.post('/api/v1/g2c/generate', json={'generator_type': 'e2a_inherited', 'runtime': 'python',
                                               'agent_name': 'ApiAgent', 'output_path': d9})
    check('POST /generate chains through the workflow', resp.status_code == 200 and resp.json()['success'])
    check('invalid request -> 400', c.post('/api/v1/g2c/e2a/abstract', json={'runtime': 'cobol', 'output_path': d9}).status_code == 400)
except ImportError:
    print('SKIP router checks (fastapi not installed)')

print(f'\n{ok} checks passed')
