"""Integration: E2A's AIDLCPipelineOrchestrator running the REAL G2C, P0
and A2C modules of this repository (no stubs) — Phase A (G2C + P0 inline),
Phase B (A2C SDLCWorkflow), Phase C (E2A static verification).
Needs e2a-framework/reference (E2A_REFERENCE_PATH or a sibling checkout).
Run: python smoke_test_aidlc_integration.py"""
import json, os, sys, tempfile, logging
HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.getenv('E2A_REFERENCE_PATH'), os.path.join(HERE, '..', 'e2a-framework', 'reference'),
             os.path.join(HERE, '..', 'subhamviky', 'e2a-framework', 'reference')):
    if cand and os.path.isfile(os.path.join(cand, 'ai_dlc_pipeline.py')):
        sys.path[:0] = [HERE, cand]
        break
else:
    print('SKIP: ai_dlc_pipeline.py not found (set E2A_REFERENCE_PATH)'); sys.exit(0)
logging.disable(logging.ERROR)
from e2a_base import BaseLLMAgentService
from e2a_inmemory_adapters import InMemoryIdempotencyStore, InMemoryTransactionalStore
import generator_templates as T
import ai_dlc_pipeline as A
from a2c_base import MANDATORY_NFRS

CODE = 'import structlog, signal, pybreaker\nfrom tenacity import retry\nlog = structlog.get_logger()\nb = pybreaker.CircuitBreaker()\ndef h(): return "/health"\ndef s(store, request_id): store.claim(request_id)\nsignal.signal(signal.SIGTERM, None)\n'
class LLM(BaseLLMAgentService):
    calls = 0
    async def _dispatch_upstream_call(self, messages, model_id, *a, **k):
        LLM.calls += 1
        sysm, user = messages[0]['content'], messages[-1]['content']
        if 'E2A Architecture Framework base abstract' in sysm: t = T.e2a_abstract('python')
        elif 'inherited E2A agent' in sysm: t = T.inherited('e2a_inherited', 'python', 'SettlementAgent', 'from common.e2a_base import BaseAgent')
        elif 'requirements architect' in sysm: t = 'Clean Architecture layers\n' + '\n'.join(MANDATORY_NFRS)
        elif 'infrastructure engineer' in sysm: t = 'resource "aws_sqs_queue" "dlq" { name = "x" }\n' * 4
        elif 'CI/CD engineer' in sysm: t = 'on:\n push:\npermissions:\n  id-token: write\njobs:\n  scan: [trivy]\n  deploy: [x]\n'
        elif 'senior architect' in sysm: t = json.dumps({'score': 0.95, 'missing': []})
        else: t = CODE
        return {'text': t, 'metadata': {'tokens_used': 20}}
    async def _dispatch_upstream_stream(self, *a, **k):
        yield ''

out = tempfile.mkdtemp()
from e2a_inmemory_adapters import InMemoryTransactionalStore
cfg = {'llm_service': LLM(), 'idempotency_store': InMemoryIdempotencyStore(),
       'artifact_store': InMemoryTransactionalStore()}
req = {'tenant_id': 't1',
       'harness': {'generator_type': 'e2a_inherited', 'runtime': 'python', 'agent_name': 'SettlementAgent',
                   'output_path': out, 'platform': 'aws'},
       'context': {'project_name': 'SettlementEngine', 'package_name': 'settlement_engine', 'runtime': 'python',
                   'build_tool': 'poetry', 'platform': 'aws'},
       'prompt': {'user_prompt': 'Charge-to-settlement reconciliation'},
       'a2c_sdlc': {'enabled': True, 'project_type': 'FastAPI Microservice', 'mandatory_nfrs': ['Audit']}}
ok = 0
def check(name, cond):
    global ok
    assert cond, name
    ok += 1
    print('PASS', name)

r = A.AIDLCPipelineOrchestrator(config=cfg).execute_pipeline(req, cfg)
gr, sr = r.get('generator_result') or {}, r.get('sdlc_result') or {}
check('build reaches E2A_VERIFIED', r.get('success') and r.get('phase_reached') == 'E2A_VERIFIED')
check('Phase A: DeveloperPlatformWorkflow(config=...) returns a flat GeneratorResult', gr.get('status') == 'generated')
check('Phase A: P0 ran inline and the class is inside the scaffold',
      gr['generated_files'][-1].endswith('settlement_engine/agents/settlement_agent.py'))
check('Phase A: P0 claim does not collide with the orchestrator claim', gr['scaffold_result']['status'] == 'scaffolded')
check('Phase B: A2C SDLCWorkflow generated and wrote artifacts',
      sr.get('status') == 'GENERATED' and len(sr.get('artifacts') or {}) == 6)
root = gr['scaffold_result']['project_root']
check('Phase B artifacts are in the P0 workspace', os.path.isfile(os.path.join(root, 'infra', 'main.tf'))
      and os.path.isfile(os.path.join(root, '.github', 'workflows', 'a2c-ci.yml')))
check('tenant given only on the build request reaches G2C, P0 and A2C',
      gr['scaffold_result']['dev_request']['tenant_id'] == 't1' and r['dev_request']['tenant_id'] == 't1')
rec = cfg['artifact_store'].get_versioned('artifact:' + gr['abstract_class_path'])[0]
check('one ownership record, written by G2C with its own key', rec['refs'] == [gr['generator_key']]
      and rec['created_by'] == gr['generator_key'])
check('build claim namespaced aidlc:, inner claims g2c:/p0:/a2c:',
      cfg['idempotency_store'].state_of('aidlc:SettlementEngine:python:poetry:aws', 't1') == 'SUCCEEDED')
check('A2C ran on a copy: the build\'s dev_request is not enriched', 'generated_code' not in r['dev_request'])

# A2C requested but impossible -> rejected up front, never a silent skip
bad = dict(req, harness=dict(req['harness'], generator_type='e2a_abstract'))
r2 = A.AIDLCPipelineOrchestrator(config=cfg).execute_pipeline(bad, cfg)
check('A2C enabled with an abstract-only harness is REJECTED_INVALID', r2['phase_reached'] == 'REJECTED_INVALID')

# Compensation vs replay: a saga that really deletes the orphaned base (opt-in);
# a retried build must not replay the deleted file as if it existed.
import shutil
class RealDelete(A.AIDLCSagaCompensator):
    def _delete_object(self, path, config):
        os.remove(path)
class FailC:
    def run_pipeline(self, config, **k): return {'status': 'FAILED', 'error': 'scan'}
out2 = tempfile.mkdtemp()
cfg2 = {'llm_service': LLM(), 'idempotency_store': InMemoryIdempotencyStore(),
        'artifact_store': InMemoryTransactionalStore(), 'saga_compensator': RealDelete(),
        'compensation_delete_orphan_abstract': True, 'static_pipeline': FailC()}
req2 = {'tenant_id': 't2', 'harness': dict(req['harness'], output_path=out2),
        'context': dict(req['context'], project_name='Solo', package_name='solo'), 'prompt': req['prompt']}
r3 = A.AIDLCPipelineOrchestrator(config=cfg2).execute_pipeline(req2, cfg2)
base = r3['generator_result']['abstract_class_path']
check('Phase C failure (no A2C): G2C_P0_DONE compensated, scaffold kept',
      r3['phase_reached'] == 'G2C_P0_DONE' and os.path.isfile(os.path.join(r3['generator_result']['project_root'], 'pyproject.toml')))
check('opt-in: the sole creator\'s orphaned base is deleted', not os.path.exists(base))
cfg2['static_pipeline'] = None
r4 = A.AIDLCPipelineOrchestrator(config=cfg2).execute_pipeline(req2, cfg2)
check('retrying the same build replays outputs that still exist (class and project copy of the base)',
      r4['success'] and r4['generator_result']['status'] == 'replay')
req3 = dict(req2, context=dict(req2['context'], project_name='Second', package_name='second'),
            harness=dict(req2['harness'], agent_name='SecondAgent'))
r5 = A.AIDLCPipelineOrchestrator(config=cfg2).execute_pipeline(req3, cfg2)
check('a new project never replays the deleted shared base: typed recovery_required, not a false success',
      not r5['success'] and r5['phase_reached'] == 'FAILED_G2C_P0'
      and r5['generator_result']['status'] == 'recovery_required'
      and 'missing' in r5['generator_result']['errors'][0])
print(f'\n{ok} checks passed')
