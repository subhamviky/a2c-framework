"""Smoke tests for the concurrency behaviour of the G2C generators, the P0
bootstrapper and DeveloperPlatformWorkflow (G2C Section 17, P0 Section 4.1,
A2C Section 3.5). In-memory test doubles only: nothing here is validated
against a live distributed store, a live model gateway or production load.
Run: python smoke_test_generator_concurrency.py"""
import os, sys, tempfile, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from a2c_concurrency import (InMemoryClaimStore, InMemoryArtifactRegistry, Deadline,
                             register_artifact, release_artifact, ClaimGuard)
from e2a_abstract_class_generator import E2AAbstractClassGenerator
from e2a_inherited_class_generator import E2AInheritedClassGenerator
from developer_platform_workflow import DeveloperPlatformWorkflow
from generator_critic_agent import GeneratorCriticAgent
from base_project_bootstrapper import PythonPoetryBootstrapper

ok = 0
def check(name, cond):
    global ok
    assert cond, name
    ok += 1
    print('PASS', name)

import generator_templates as T
TMP = tempfile.mkdtemp()
# A model reply that passes the structural critic for every generator type used
# below: the E2A skeleton plus an inherited 'Refund' class.
VALID = T.e2a_abstract('python') + '\n\n' + T.inherited(
    'e2a_inherited', 'python', 'Refund', '').replace('import logging\n', 'import logging')

class FakeLLMService:
    """Stands in for E2A's BaseLLMAgentService: async process_inference that
    reports failures as {'status': 'FAILED'} instead of raising."""
    def __init__(self, text=VALID, delay=0.0, fail_with=None):
        self.text, self.delay, self.fail_with = text, delay, fail_with
        self.calls, self.lock, self.last = 0, threading.Lock(), None
    async def process_inference(self, messages, tenant_id=None, deadline=None, **kw):
        import asyncio
        with self.lock:
            self.calls += 1
            self.last = dict(tenant_id=tenant_id, deadline=deadline, kw=kw)
        await asyncio.sleep(self.delay)
        if self.fail_with:
            return {'status': 'FAILED', 'error': 'no capacity', 'error_type': self.fail_with,
                    'physical_success': False}
        return {'status': 'SUCCESS', 'text': self.text, 'physical_success': True}

class ScoredGen(E2AAbstractClassGenerator):
    """Critic returns scripted scores to exercise the regeneration loop."""
    def __init__(self, scores): self.scores, self.n = list(scores), 0
    def _evaluate_output(self, response, request, config=None, **kw):
        self.n += 1
        return self.scores.pop(0) if self.scores else 0.0

class WriteFails(E2AAbstractClassGenerator):
    def _write_output(self, *a, **k): raise OSError('disk full')

def req(**o):
    r = {'generator_type': 'e2a_abstract', 'runtime': 'python', 'output_path': TMP + '/out',
         'agent_name': 'Refund', 'tenant_id': 't1'}
    r.update(o); return r

# ---- 1 happy path, claim settled succeeded, model called via llm_service only
store, llm = InMemoryClaimStore(), FakeLLMService()
cfg = {'idempotency_store': store, 'llm_service': llm}
g = E2AAbstractClassGenerator()
r1 = g.generate(req(), cfg)
check('generate succeeds through llm_service', r1['success'] and r1['status'] == 'generated' and llm.calls == 1)
check('tenant and correlation reach the gateway', llm.last['tenant_id'] == 't1')
key = r1['generator_key']
check('generator_key is name:type:runtime:platform', key == 'Refund:e2a_abstract:python:standalone')
check('claim settled SUCCEEDED', store.state_of('g2c:' + key, 't1') == 'SUCCEEDED')

# ---- 2 replay: idempotent no-op, no second model call, no second write
r2 = g.generate(req(), cfg)
check('replay returns stored result without a model call', r2['status'] == 'replay' and r2.get('replayed') and llm.calls == 1)

# ---- 3 conflict: same key, different request
r3 = g.generate(req(output_path=TMP + '/other'), cfg)
check('same key with different request is a conflict', r3['status'] == 'conflict' and not r3['success'])

# ---- 4 tenant scoping: another tenant does not collide
r4 = g.generate(req(tenant_id='t2'), cfg)
check('tenants do not collide on the same generator_key', r4['status'] == 'generated' and llm.calls == 2)

# ---- 5 concurrent duplicates: exactly one generates, the rest in_progress/replay
store, llm = InMemoryClaimStore(), FakeLLMService(delay=0.2)
cfg = {'idempotency_store': store, 'llm_service': llm}
outs, bar = [], threading.Barrier(8)
def worker():
    bar.wait(); outs.append(E2AAbstractClassGenerator().generate(req(), cfg))
ts = [threading.Thread(target=worker) for _ in range(8)]
[t.start() for t in ts]; [t.join() for t in ts]
gen = [o for o in outs if o['status'] == 'generated']
check('8 concurrent identical requests: exactly one generation', len(gen) == 1 and llm.calls == 1)
check('the others get a prompt typed outcome, none starts a second run',
      all(o['status'] in ('in_progress', 'replay') for o in outs if o is not gen[0]))

# ---- 6 model rejection settles retryable, then a retry succeeds
store = InMemoryClaimStore()
bad = FakeLLMService(fail_with='AdmissionTimeout')
cfg = {'idempotency_store': store, 'llm_service': bad}
r = E2AAbstractClassGenerator().generate(req(), cfg)
check('rejected model call is a typed retryable outcome', r['status'] == 'inference_rejected' and r['retryable'])
check('claim settled FAILED_RETRYABLE', store.state_of('g2c:' + r['generator_key'], 't1') == 'FAILED_RETRYABLE')
r = E2AAbstractClassGenerator().generate(req(), {'idempotency_store': store, 'llm_service': FakeLLMService()})
check('retry after a rejection generates', r['status'] == 'generated')

# ---- 7 deadline
store, llm = InMemoryClaimStore(), FakeLLMService()
r = E2AAbstractClassGenerator().generate(req(deadline_ms=0), {'idempotency_store': store, 'llm_service': llm})
check('expired deadline stops before any model call', r['status'] == 'deadline_exceeded' and llm.calls == 0)
check('deadline-cancelled run settles retryable', store.state_of('g2c:' + r['generator_key'], 't1') == 'FAILED_RETRYABLE')
llm2 = FakeLLMService()
E2AAbstractClassGenerator().generate(req(agent_name='D2', deadline_ms=5000, output_path=TMP + '/d2'), {'llm_service': llm2})
check('deadline is passed to the gateway', llm2.last['deadline'] is not None and llm2.last['deadline'].remaining() > 0)

# ---- 8 critic regeneration: max 2 retries, then final
store, llm = InMemoryClaimStore(), FakeLLMService()
cfg = {'idempotency_store': store, 'llm_service': llm}
sg = ScoredGen([0.1, 0.9]); r = sg.generate(req(), cfg)
check('low score regenerates once and then passes', r['success'] and r['critic_report']['attempts'] == 2 and llm.calls == 2)
store, llm = InMemoryClaimStore(), FakeLLMService()
sg = ScoredGen([0.1, 0.1, 0.1, 0.1]); r = sg.generate(req(), {'idempotency_store': store, 'llm_service': llm})
check('critic below threshold after two retries stops at 3 attempts', r['status'] == 'critic_threshold_not_met' and llm.calls == 3)
check('critic failure settles FAILED_FINAL', store.state_of('g2c:' + r['generator_key'], 't1') == 'FAILED_FINAL')
r = ScoredGen([1.0]).generate(req(), {'idempotency_store': store, 'llm_service': llm})
check('a final failure is not re-executed', r['status'] == 'failed_final' and llm.calls == 3)

# ---- 9 failure after writing began parks UNKNOWN; expired owner needs reconciliation
store = InMemoryClaimStore()
try:
    WriteFails().generate(req(), {'idempotency_store': store, 'llm_service': FakeLLMService()})
    check('write failure propagates', False)
except OSError:
    check('write failure propagates', True)
check('failure after writing began parks UNKNOWN', store.state_of('g2c:' + 'Refund:e2a_abstract:python:standalone', 't1') == 'UNKNOWN')
r = E2AAbstractClassGenerator().generate(req(), {'idempotency_store': store, 'llm_service': FakeLLMService()})
check('UNKNOWN is left for reconciliation, never blindly re-run', r['status'] == 'recovery_required')
store = InMemoryClaimStore()
guard = ClaimGuard(store, 'g2c:k', 't1', 'fp'); guard.acquire(); store.expire_lease('g2c:k', 't1')
r = E2AAbstractClassGenerator().generate(req(agent_name='K'), {'idempotency_store': store, 'llm_service': FakeLLMService()})
check('an unrelated key is unaffected by another expired claim', r['status'] == 'generated')

# ---- 10 stale owner cannot settle a key whose lease was taken over
store = InMemoryClaimStore()
a = ClaimGuard(store, 'x', 't1', 'fp', lease_seconds=300); a.acquire()
store.expire_lease('x', 't1')
b = store.claim('x', None, tenant_id='t1', fingerprint='fp', owner='reconciler', recover=True)
check('reconciler takes over an expired claim', b.status.value == 'CLAIMED')
check('stale owner cannot complete the key', store.complete('x', {'late': True}, tenant_id='t1', owner=a.owner) is False)

# ---- 11 no store, no gateway: simplified stub path still works
r = E2AAbstractClassGenerator().generate(req(agent_name='Plain', output_path=TMP + '/plain'), {})
check('stub path without store or gateway still generates', r['success'])
try:
    E2AAbstractClassGenerator().generate({**req(), 'tenant_id': None}, {'llm_service': FakeLLMService()})
    check('tenant required when a gateway is used', False)
except ValueError:
    check('tenant required when a gateway is used', True)

# ---- 12 shared abstract class: CAS ownership
reg = InMemoryArtifactRegistry()
register_artifact(reg, 'common/e2a_base.py', 'A', created_fresh=True)
register_artifact(reg, 'common/e2a_base.py', 'B', created_fresh=False)
check('creator releasing while another reference remains does not delete', release_artifact(reg, 'common/e2a_base.py', 'A') is False)
check('non-creator releasing the last reference does not delete', release_artifact(reg, 'common/e2a_base.py', 'B') is False)
reg = InMemoryArtifactRegistry()
register_artifact(reg, 'p', 'A', created_fresh=True)
check('creator releasing the last reference may delete', release_artifact(reg, 'p', 'A') is True)
check('an already-deleted artifact is not deleted twice', release_artifact(reg, 'p', 'A') is False)
reg = InMemoryArtifactRegistry()
register_artifact(reg, 'pkg', 'A', created_fresh=False)
check('artifact loaded from path/package is never removable', release_artifact(reg, 'pkg', 'A') is False)
# race: creator and a co-reference release at the same instant -> at most one deletion ever
wins = []
for trial in range(200):
    reg = InMemoryArtifactRegistry()
    register_artifact(reg, 'q', 'A', created_fresh=True); register_artifact(reg, 'q', 'B', created_fresh=False)
    bar = threading.Barrier(2); res = []
    def rel(k):
        bar.wait(); res.append(release_artifact(reg, 'q', k))
    t1, t2 = threading.Thread(target=rel, args=('A',)), threading.Thread(target=rel, args=('B',))
    t1.start(); t2.start(); t1.join(); t2.join(); wins.append(sum(res))
check('200 racing releases: never more than one deletion', max(wins) <= 1)

# ---- 13 workflow: chain, registry, compensation
# v1.3: the chain is a2c_inherited (E2A base, A2C base, subclass: three model calls); the template
# model answers each prompt with its curated class, and a counter wraps it
from a2c_template_llm import build_template_llm
class ChainLLM:
    def __init__(self):
        self.inner, self.calls = build_template_llm(), 0
    async def process_inference(self, messages, **kw):
        self.calls += 1
        return await self.inner.process_inference(messages, **kw)
tmp = tempfile.mkdtemp()
store, llm = InMemoryClaimStore(), ChainLLM()
wf = DeveloperPlatformWorkflow(artifact_registry=InMemoryArtifactRegistry())
cfg = {'idempotency_store': store, 'llm_service': llm}
rq = {'generator_type': 'a2c_inherited', 'runtime': 'python', 'agent_name': 'Refund',
      'output_path': tmp + '/', 'tenant_id': 't1'}
wreq = dict(rq)
out = wf.generate(wreq, cfg)
check('workflow chains abstract then inherited', out['success'] and out['status'] == 'generated' and llm.calls == 3)
out2 = wf.generate(dict(rq), cfg)
check('workflow replay is the idempotent no-op (no model call)', out2.get('replayed') and llm.calls == 3)
shared_path = out['abstract_class_path']
abstract_path = tmp + '/common/e2a_base.py'
os.makedirs(tmp + '/common', exist_ok=True); open(abstract_path, 'w').write('# abstract')
used = {**rq, 'abstract_class_path': abstract_path}
rec = wf.artifact_registry.get(shared_path)
check('workflow records the shared abstract class ownership', rec is not None and len(rec['refs']) == 1 and rec['creator'] == rec['refs'][0])
# compensation of a request that loaded its abstract class from a path never deletes it
wf2 = DeveloperPlatformWorkflow(artifact_registry=InMemoryArtifactRegistry())
register_artifact(wf2.artifact_registry, abstract_path, 'Other:e2a_inherited:python:standalone', created_fresh=False)
comp = wf2.compensate(used, {'output': {'generator_key': 'Other:e2a_inherited:python:standalone'}})
check('compensation never deletes a loaded abstract class', os.path.isfile(abstract_path) and comp['removed'] is False)
register_artifact(wf2.artifact_registry, abstract_path, 'Fresh:e2a_inherited:python:standalone', created_fresh=True)
comp = wf2.compensate(used, {'output': {'generator_key': 'Fresh:e2a_inherited:python:standalone'}})
check('creator with no other reference removes its own fresh abstract class', comp['removed'] and not os.path.exists(abstract_path))

# ---- 14 critic static concurrency rules
c = GeneratorCriticAgent()
clean = 'class A:\n    async def run(self):\n        return await self._infer(m, cfg)\n'
check('clean generated code scores 1.0', c.score(clean, {}) == 1.0)
bad = 'import asyncio\nimport openai\nsem = asyncio.Semaphore(4)\nclass A:\n    def _validate_state(self): pass\n'
check('own semaphore, provider SDK and _validate_state are all flagged', len(c.concurrency_findings(bad)) == 3 and c.score(bad, {}) < 0.75)

# ---- 15 P0: concurrent bootstrap, replay, conflict, rescaffold serialisation
def boot_req(d, **o):
    r = {'project_name': 'svc', 'runtime': 'python', 'build_tool': 'poetry', 'platform': 'aws',
         'package_name': 'svc', 'output_path': d, 'tenant_id': 't1'}
    r.update(o); return r
d = tempfile.mkdtemp(); store = InMemoryClaimStore()
cfg = {'idempotency_store': store, 'output_path': d}
class SlowBoot(PythonPoetryBootstrapper):
    def _generate_readme_scaffold(self, request, config=None, **kw):
        time.sleep(0.2); return super()._generate_readme_scaffold(request, config, **kw)
outs, bar = [], threading.Barrier(6)
def boot():
    bar.wait(); outs.append(SlowBoot(cfg).bootstrap(boot_req(d), cfg))
ts = [threading.Thread(target=boot) for _ in range(6)]
[t.start() for t in ts]; [t.join() for t in ts]
done = [o for o in outs if o.get('status') == 'scaffolded']
check('6 concurrent bootstraps of one target: exactly one writes', len(done) == 1)
check('the others return in_progress or replay and write nothing',
      all(o.get('status') in ('in_progress', 'replay') for o in outs if o is not done[0]))
check('claim settled SUCCEEDED after Step 14', store.state_of('p0:' + done[0]['scaffold_key'], 't1') == 'SUCCEEDED')
rr = SlowBoot(cfg).bootstrap(boot_req(d), cfg)
check('replay returns the stored ScaffoldResult', rr['status'] == 'replay' and rr['replayed'] and rr['scaffold_key'] == done[0]['scaffold_key'])
rc = SlowBoot(cfg).bootstrap(boot_req(d, license='MIT'), cfg)
check('same key, different request: conflict', rc['status'] == 'conflict' and not rc['success'])

# a validation failure at Step 14 settles final; a partial scaffold is never blindly re-run
d2 = tempfile.mkdtemp(); store2 = InMemoryClaimStore(); cfg2 = {'idempotency_store': store2, 'output_path': d2}
class BadOutput(PythonPoetryBootstrapper):
    def _validate_output(self, result, config=None, **kw): return False
r = BadOutput(cfg2).bootstrap(boot_req(d2), cfg2)
check('output validation failure returns success=False', r['success'] is False)
check('output validation failure settles FAILED_FINAL', store2.state_of('p0:' + 'svc:python:poetry:aws', 't1') == 'FAILED_FINAL')
class Crash(PythonPoetryBootstrapper):
    def _generate_makefile(self, *a, **k): raise RuntimeError('boom')
d3 = tempfile.mkdtemp(); store3 = InMemoryClaimStore(); cfg3 = {'idempotency_store': store3, 'output_path': d3}
r = Crash(cfg3).bootstrap(boot_req(d3), cfg3)
check('failure after files began parks UNKNOWN', store3.state_of('p0:' + 'svc:python:poetry:aws', 't1') == 'UNKNOWN')
r = PythonPoetryBootstrapper(cfg3).bootstrap(boot_req(d3), cfg3)
check('UNKNOWN scaffold is left for reconciliation', r['status'] == 'recovery_required')
# failure before Step 5 is retryable
class EarlyFail(PythonPoetryBootstrapper):
    def _plan_scaffold(self, *a, **k): raise RuntimeError('plan failed')
d4 = tempfile.mkdtemp(); store4 = InMemoryClaimStore(); cfg4 = {'idempotency_store': store4, 'output_path': d4}
EarlyFail(cfg4).bootstrap(boot_req(d4), cfg4)
check('failure before Step 5 settles retryable', store4.state_of('p0:' + 'svc:python:poetry:aws', 't1') == 'FAILED_RETRYABLE')
r = PythonPoetryBootstrapper(cfg4).bootstrap(boot_req(d4), cfg4)
check('and a retry then succeeds', r['status'] == 'scaffolded')

# idempotency=False: deliberate re-scaffolds still serialise, but can repeat sequentially
class Again(SlowBoot): idempotency = False
d5 = tempfile.mkdtemp(); store5 = InMemoryClaimStore(); cfg5 = {'idempotency_store': store5, 'output_path': d5}
outs, bar = [], threading.Barrier(3)
def again():
    bar.wait(); outs.append(Again(cfg5).bootstrap(boot_req(d5), cfg5))
ts = [threading.Thread(target=again) for _ in range(3)]
[t.start() for t in ts]; [t.join() for t in ts]
check('idempotency=False still serialises concurrent re-scaffolds', sum(1 for o in outs if o.get('status') == 'scaffolded') == 1)
r = Again(cfg5).bootstrap(boot_req(d5), cfg5)
check('idempotency=False allows a later deliberate re-scaffold', r['status'] == 'scaffolded')

# the stored result carries dev_request, so a replay feeds the same A2C hand-off
d6 = tempfile.mkdtemp(); store6 = InMemoryClaimStore()
cfg6 = {'idempotency_store': store6, 'output_path': d6, 'a2c': {'enabled': True}}
first = PythonPoetryBootstrapper(cfg6).bootstrap(boot_req(d6), cfg6)
again_ = PythonPoetryBootstrapper(cfg6).bootstrap(boot_req(d6), cfg6)
check('replay returns the same dev_request for the A2C phase', again_['status'] == 'replay' and again_.get('dev_request') == first.get('dev_request') and first.get('dev_request'))

# no store: legacy single-process behaviour unchanged
d7 = tempfile.mkdtemp(); cfg7 = {'output_path': d7}
a = PythonPoetryBootstrapper(cfg7).bootstrap(boot_req(d7), cfg7)
b = PythonPoetryBootstrapper(cfg7).bootstrap(boot_req(d7), cfg7)
check('without a store: first writes, second skips by directory check', a['success'] and b['success'] and b.get('replayed'))

print(f'\n{ok} checks passed')
