"""Smoke tests for a2c_base.py (A2C) and the P0 -> A2C composition.

Needs e2a-framework/reference on the import path: set E2A_REFERENCE_PATH, or
check out e2a-framework next to this repository. In-memory test doubles
only — no live model gateway, store or production load.
Run: python smoke_test_a2c.py"""
import asyncio, json, os, sys, tempfile, threading
HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.getenv('E2A_REFERENCE_PATH'), os.path.join(HERE, '..', 'e2a-framework', 'reference'),
             os.path.join(HERE, '..', 'subhamviky', 'e2a-framework', 'reference')):
    if cand and os.path.isfile(os.path.join(cand, 'e2a_base.py')):
        sys.path.insert(0, cand)
        break
else:
    print('SKIP: e2a_base.py not found (set E2A_REFERENCE_PATH)'); sys.exit(0)
sys.path.insert(0, HERE)

from e2a_base import BaseLLMAgentService
from e2a_inmemory_adapters import InMemoryIdempotencyStore
from a2c_base import (SDLCWorkflow, DevPlatformValidationService, LocalArtifactWriter, MANDATORY_NFRS,
                      nfr_pattern_report, artifact_paths)
from base_project_bootstrapper import BootstrapAndGenerateWorkflow
import generator_templates as T
from generator_critic_agent import GeneratorCriticAgent

ok = 0
def check(name, cond):
    global ok
    assert cond, name
    ok += 1
    print('PASS', name)

GOOD_CODE = '''import logging, signal, structlog
from opentelemetry import trace
import pybreaker
from tenacity import retry, wait_exponential_jitter
log = structlog.get_logger()
breaker = pybreaker.CircuitBreaker(fail_max=5)
class SettlementService:
    def settle(self, request_id, store):
        if not store.claim(request_id): return
    @retry(wait=wait_exponential_jitter())
    def call(self): ...
def health(): return {"path": "/health"}
signal.signal(signal.SIGTERM, lambda *a: None)
'''
COMMENT_ONLY = '''# idempotency, circuit breaker, retry, /health, SIGTERM, structlog
class SettlementService:
    def settle(self): return 1
'''

class FakeLLM(BaseLLMAgentService):
    """Answers per agent role (read from the system prompt)."""
    def __init__(self, weak=0, critic_score=0.9, **k):
        super().__init__(**k)
        self.weak, self.critic_score, self.calls, self.models = weak, critic_score, 0, []
        self.lock = threading.Lock()
    async def _dispatch_upstream_call(self, messages, model_id, temperature, max_tokens, tools,
                                      stop_sequences, cache_handle, config, **kw):
        with self.lock:
            self.calls += 1; self.models.append(model_id)
        sysmsg, user = messages[0]['content'], messages[-1]['content']
        if 'requirements architect' in sysmsg:
            text = '# Spec\nLayers: model, contract, service, exposure (Clean Architecture).\n' + \
                   '\n'.join(f'- {n}' for n in MANDATORY_NFRS + ['Audit'])
        elif 'infrastructure engineer' in sysmsg:
            text = ('resource "aws_sqs_queue" "dlq" { name = "svc-dlq" }\n'
                    'resource "aws_sqs_queue" "main" { name = "svc"\n redrive_policy = "dlq" }\n'
                    'variable "db_password" {}\n')
        elif 'CI/CD engineer' in sysmsg:
            text = ('on:\n  push:\npermissions:\n  id-token: write\njobs:\n  build:\n    steps:\n'
                    '      - run: make test\n      - uses: aquasecurity/trivy-action@v1\n  deploy:\n    steps: [run: deploy]\n')
        elif 'senior architect' in sysmsg:
            text = json.dumps({'score': self.critic_score, 'missing': [], 'passed': MANDATORY_NFRS})
        else:
            fixed = 'previous version failed review' in user
            weak = bool(self.weak) and (self.weak == 'always' or not fixed)
            text = COMMENT_ONLY if weak else GOOD_CODE
        return {'text': text, 'metadata': {'tokens_used': 50}}
    async def _dispatch_upstream_stream(self, *a, **k):
        yield ''

def dev(root=None, **o):
    d = {'project_name': 'SettlementEngine', 'project_type': 'FastAPI Microservice',
         'mandatory_nfrs': ['Audit'], 'context': 'settlement', 'target_cloud': 'aws',
         'language': 'python', 'tenant_id': 't1'}
    if root: d['project_root'] = root
    d.update(o); return d

# ---- 1 validation runs before the workflow
v = DevPlatformValidationService()
check('valid DevRequest passes validation', v.validate('SDLCAssistantAgent', dev())['valid'])
bad = v.validate('SDLCAssistantAgent', {'project_name': 'x'})
check('missing fields are a ValidationResult, not an exception',
      not bad['valid'] and any('tenant_id' in e for e in bad['errors']))

# ---- 2 happy path, NFR-first order, artifacts written, claim settled
root, store, llm = tempfile.mkdtemp(), InMemoryIdempotencyStore(), FakeLLM()
cfg = {'llm_service': llm, 'idempotency_store': store, 'critic_model_id': 'small-model'}
r = SDLCWorkflow(config=cfg).execute(dev(root), cfg)
check('workflow generates', r.get('status') == 'GENERATED' and not r.get('errors'))
check('NFR-first order: 7 agent runs', llm.calls == 7)
check('mandatory NFRs injected before any model call', set(MANDATORY_NFRS) <= set(r['mandatory_nfrs']) and 'Audit' in r['mandatory_nfrs'])
check('generation_key set by _apply_policy', r['generation_key'] == 'SettlementEngine:FastAPI Microservice:aws')
check('critic score is min(model, pattern check)', r['critic_report']['score'] == 0.9 and r['critic_report']['pattern_check']['score'] == 1.0)
check('critic runs on the cheaper model', llm.models[-1] == 'small-model')
paths = artifact_paths(r, cfg)
check('artifacts written into the P0 workspace', all(os.path.isfile(os.path.join(root, paths[f])) for f in
      ('generated_code', 'generated_iac', 'generated_cicd', 'spec')))
check('claim settled SUCCEEDED', store.state_of(r['idempotency_key'], 't1') == 'SUCCEEDED')

# ---- 3 replay: no model call, artifacts in response
r2 = SDLCWorkflow(config=cfg).execute(dev(root), cfg)
check('duplicate request replays without a model call', r2.get('replayed') and llm.calls == 7)
check('replay carries the artifacts in response', 'generated_iac' in r2['response'] and r2['response']['status'] == 'GENERATED')

# ---- 4 governance: unapproved cloud never reaches the model
llm4 = FakeLLM(); cfg4 = {'llm_service': llm4}
r = SDLCWorkflow(config=cfg4).execute(dev(target_cloud='onprem'), cfg4)
check('unapproved cloud stops the run before a model call', r['status'] == 'AGENT_FAILED' and llm4.calls == 0
      and any('not approved' in e for e in r['errors']))

# ---- 5 NFRs only in comments: critic fails, business code regenerated with findings
root5, llm5 = tempfile.mkdtemp(), FakeLLM(weak=1)
cfg5 = {'llm_service': llm5}
r = SDLCWorkflow(config=cfg5).execute(dev(root5), cfg5)
check('comment-only NFRs fail the pattern check', nfr_pattern_report(COMMENT_ONLY, MANDATORY_NFRS)['score'] < 0.5)
check('one regeneration fixes it', r['status'] == 'GENERATED' and r['critic_report']['regenerations'] == 1 and llm5.calls == 9)

# ---- 6 never fixed: final failure, nothing written
root6, llm6 = tempfile.mkdtemp(), FakeLLM(weak='always')
cfg6 = {'llm_service': llm6, 'idempotency_store': InMemoryIdempotencyStore()}
r = SDLCWorkflow(config=cfg6).execute(dev(root6), cfg6)
check('critic below threshold after 2 regenerations', r['status'] == 'CRITIC_THRESHOLD_NOT_MET' and llm6.calls == 11)
check('nothing is written when the critic fails', not any(os.scandir(root6)))

# ---- 7 competing writer: conditional write is a typed conflict
class Racer(LocalArtifactWriter):
    def __init__(self, at): self.at, self.n = at, 0
    def write(self, root, rel, content, expected_version):
        self.n += 1
        if self.n == self.at:      # another request writes this path first
            p = os.path.join(root, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, 'w').write('other writer\n')
        return super().write(root, rel, content, expected_version)
root7, store7 = tempfile.mkdtemp(), InMemoryIdempotencyStore()
cfg7 = {'llm_service': FakeLLM(), 'idempotency_store': store7}
r = SDLCWorkflow(config=cfg7, writer=Racer(1)).execute(dev(root7), cfg7)
check('conflict on the first write: typed, nothing committed', r['status'] == 'ARTIFACT_CONFLICT'
      and store7.state_of(r['idempotency_key'], 't1') == 'FAILED_RETRYABLE')
root8, store8 = tempfile.mkdtemp(), InMemoryIdempotencyStore()
cfg8 = {'llm_service': FakeLLM(), 'idempotency_store': store8}
r = SDLCWorkflow(config=cfg8, writer=Racer(3)).execute(dev(root8), cfg8)
check('conflict after earlier writes: parked UNKNOWN for reconciliation',
      store8.state_of(r['idempotency_key'], 't1') == 'UNKNOWN')

# ---- 8 topology order and tenant requirement
llm9 = FakeLLM(); cfg9 = {'llm_service': llm9, 'a2c_sequence': 'topology'}
r = SDLCWorkflow(config=cfg9).execute(dev(), cfg9)
check('topology order: 5 agent runs', r['status'] == 'GENERATED' and llm9.calls == 5)
try:
    SDLCWorkflow(config=cfg9).execute({k: v for k, v in dev().items() if k != 'tenant_id'}, cfg9)
    check('tenant_id required', False)
except ValueError:
    check('tenant_id required', True)

# ---- 9 P0 -> A2C through BootstrapAndGenerateWorkflow (composable siblings)
out = tempfile.mkdtemp(); llm10 = FakeLLM()
cfg10 = {'output_path': out, 'llm_service': llm10, 'tenant_id': 't1',
         'a2c': {'enabled': True, 'project_type': 'FastAPI Microservice', 'mandatory_nfrs': ['Audit'],
                 'context': 'settlement'}}
res = BootstrapAndGenerateWorkflow(cfg10).execute(
    {'project_name': 'Settle', 'package_name': 'settle', 'runtime': 'python', 'build_tool': 'poetry',
     'platform': 'aws'}, cfg10)
gen = res.get('generation_result') or {}
check('bootstrap then generate', res['success'] and gen.get('status') == 'GENERATED')
check('A2C artifacts land in the P0 workspace',
      os.path.isfile(os.path.join(out, 'Settle', 'infra', 'main.tf')) and
      os.path.isfile(os.path.join(out, 'Settle', 'pyproject.toml')))

# ---- 10 G2C emits this file as the Python A2C base, and it passes the G2C critic
src = T.a2c_abstract('python')
check('A2C abstract template is a2c_base.py', 'class SDLCWorkflow(BaseWorkflow)' in src)
check('a2c_base.py passes GeneratorCriticAgent (a2c_abstract)',
      GeneratorCriticAgent().score(src, {'generator_type': 'a2c_abstract', 'runtime': 'python'}) >= 0.75)

print(f'\n{ok} checks passed')
