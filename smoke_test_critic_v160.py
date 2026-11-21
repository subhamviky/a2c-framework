"""A2C v1.6.0 (hub design note EV-01, phase 2): the critics.

  2.2  G2C's optional semantic review (critic_model_id), combined with the structural score (lower wins)
  2.3  Node (TypeScript) and Go syntax checks; the Python NFR check reads the syntax tree
  2.4  aidlc-build says whether a failed build can simply be run again (E2A v1.9.1)

The model is a scripted test double (recorded answers replayed); nothing calls a live model.
Run: python smoke_test_critic_v160.py"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import generator_templates as T
from a2c_base import MANDATORY_NFRS, nfr_pattern_report
from a2c_concurrency import InMemoryClaimStore
from base_generator_agent import SEMANTIC_REVIEW_PROMPT
from e2a_abstract_class_generator import E2AAbstractClassGenerator
from generator_critic_agent import GeneratorCriticAgent

passed = 0


def check(name, ok, detail=''):
    global passed
    print(('PASS ' if ok else 'FAIL ') + name + (f'\n{detail}' if not ok and detail else ''))
    if not ok:
        sys.exit(1)
    passed += 1


VALID = T.e2a_abstract('python')


class ScriptedLLM:
    """Replays answers: generator calls get the generated file, critic calls get the next review."""
    def __init__(self, reviews=(), critic_fails=False):
        self.reviews, self.critic_fails = list(reviews), critic_fails
        self.generator_calls, self.critic_calls, self.lock = [], [], threading.Lock()

    async def process_inference(self, messages, tenant_id=None, deadline=None, **kw):
        await asyncio.sleep(0)
        with self.lock:
            if messages[0]['content'] == SEMANTIC_REVIEW_PROMPT:
                self.critic_calls.append(dict(kw, tenant_id=tenant_id, user=messages[1]['content']))
                if self.critic_fails:
                    return {'status': 'FAILED', 'error': 'critic model unavailable', 'error_type': 'ProviderError'}
                review = self.reviews.pop(0) if self.reviews else '{"score": 1.0, "missing": []}'
                return {'status': 'SUCCESS', 'text': review}
            self.generator_calls.append(kw)
            return {'status': 'SUCCESS', 'text': VALID}


def generate(llm, tmp, **request):
    req = {'generator_type': 'e2a_abstract', 'runtime': 'python', 'output_path': tmp, 'agent_name': 'Refund',
           'tenant_id': 't1', **request}
    return E2AAbstractClassGenerator().generate(req, {'idempotency_store': InMemoryClaimStore(), 'llm_service': llm})


# ---- 2.2 semantic review ------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    llm = ScriptedLLM()
    r = generate(llm, tmp + '/a')
    check('no critic model named: no semantic review, the structural score alone',
          r['success'] and llm.critic_calls == [] and 'semantic' not in r['critic_report'], json.dumps(r.get('critic_report')))

    llm = ScriptedLLM(['{"score": 0.9, "missing": ["_rerank ignores the query"]}'])
    r = generate(llm, tmp + '/b', critic_model_id='small-critic')
    rep = r['critic_report']
    check('critic_model_id: one review through llm_service, with that model and the run\'s claim key',
          len(llm.critic_calls) == 1 and llm.critic_calls[0]['model_id'] == 'small-critic'
          and llm.critic_calls[0]['idempotency_key'].endswith(':critic0') and llm.critic_calls[0]['tenant_id'] == 't1',
          json.dumps(llm.critic_calls, default=str)[:400])
    check('the lower score wins: min(structural, semantic), both recorded',
          r['success'] and rep['structural_score'] == 1.0 and rep['semantic']['score'] == 0.9 and rep['score'] == 0.9
          and 'semantic: _rerank ignores the query' in rep['missing'], json.dumps(rep))
    check('the review sees the generated source', 'class BaseAgent' in llm.critic_calls[0]['user'])

    llm = ScriptedLLM(['{"score": 0.2, "missing": ["hooks ignore their inputs"]}'] * 3)
    r = generate(llm, tmp + '/c', critic_model_id='small-critic')
    check('a low semantic score fails the gate even when the structure passes (after the regenerations)',
          not r['success'] and r['status'] == 'critic_threshold_not_met' and len(llm.generator_calls) == 3
          and len(llm.critic_calls) == 3, json.dumps({k: r.get(k) for k in ('status', 'errors')}))

    llm = ScriptedLLM(['not json'] * 3)
    r = generate(llm, tmp + '/d', critic_model_id='small-critic')
    check('an unreadable review scores 0.0 (never a pass by default)',
          not r['success'] and r['critic_report']['semantic']['score'] == 0.0
          and 'the semantic review was not readable JSON' in r['critic_report']['semantic']['missing'])

    llm = ScriptedLLM(critic_fails=True)
    r = generate(llm, tmp + '/e', critic_model_id='small-critic')
    check('a failed critic model call is a typed, retryable outcome (nothing was written)',
          not r['success'] and r['status'] == 'inference_rejected' and r.get('retryable') is True
          and not Path(tmp + '/e').exists(), json.dumps({k: r.get(k) for k in ('status', 'errors', 'retryable')}))

    os.environ['GENERATOR_CRITIC_MODEL_ID'] = 'env-critic'
    try:
        llm = ScriptedLLM()
        r = generate(llm, tmp + '/f')
        check('GENERATOR_CRITIC_MODEL_ID names the critic model too',
              r['success'] and [c['model_id'] for c in llm.critic_calls] == ['env-critic'])
    finally:
        del os.environ['GENERATOR_CRITIC_MODEL_ID']

    broken = ScriptedLLM()

    async def unparsable(messages, tenant_id=None, deadline=None, **kw):
        if messages[0]['content'] == SEMANTIC_REVIEW_PROMPT:
            broken.critic_calls.append(kw)
            return {'status': 'SUCCESS', 'text': '{"score": 1.0}'}
        return {'status': 'SUCCESS', 'text': 'def broken(:\n'}
    broken.process_inference = unparsable
    r = generate(broken, tmp + '/g', critic_model_id='small-critic')
    check('output the structural check scores 0.0 is not sent for review (no model spend on broken code)',
          not r['success'] and broken.critic_calls == [])

# ---- 2.3 syntax checks ----------------------------------------------------------------------------
critic = GeneratorCriticAgent({'critic_type': 'e2a_abstract'})
for runtime, tool, broken_tail in (('node', 'tsc', '\nclass X { foo( { }\n'), ('go', 'gofmt', '\nfunc x( {\n')):
    if not shutil.which(tool):
        print(f'SKIP {runtime} syntax check: {tool} is not on PATH (the critic then skips it too)')
        continue
    good = T.e2a_abstract(runtime)
    ok = critic.review(good, {'runtime': runtime})
    bad = critic.review(good + broken_tail, {'runtime': runtime})
    check(f'{runtime}: generated source parses ({tool}); a syntax error scores 0.0',
          ok['score'] == 1.0 and 'parses' in ok['passed'] and bad['score'] == 0.0
          and bad['missing'][0].startswith(f'{runtime} syntax error'), json.dumps([ok, bad])[:600])
    off = GeneratorCriticAgent({'critic_type': 'e2a_abstract', 'syntax_check': False}).review(good + broken_tail,
                                                                                            {'runtime': runtime})
    check(f'{runtime}: critic_config syntax_check=False turns the check off', 'parses' not in off['passed'])

# ---- 2.3 the Python NFR check reads the syntax tree -----------------------------------------------
REAL = '''
import logging, signal
import pybreaker
from tenacity import retry, wait_exponential
logger = logging.getLogger(__name__)
breaker = pybreaker.CircuitBreaker(fail_max=5)

@retry(wait=wait_exponential())
def handle(store, request_id):
    store.claim(request_id)

@app.get("/health")
def health():
    return {}

signal.signal(signal.SIGTERM, lambda *a: None)
'''
WORDS_ONLY = '''
"""Implements idempotency, retry with backoff, a circuit breaker, /health, graceful shutdown, otel."""
import json


def handle(x):
    print("retry with backoff later; circuit breaker; idempotent; sigterm; opentelemetry")  # retry, breaker
    return json.dumps(x)
'''
real, words = nfr_pattern_report(REAL, MANDATORY_NFRS), nfr_pattern_report(WORDS_ONLY, MANDATORY_NFRS)
check('Python NFRs implemented as code pass (read from the syntax tree)',
      real['method'] == 'ast' and real['score'] == 1.0, json.dumps(real))
check('NFRs named only in a docstring, a comment or a log message do not count',
      words['method'] == 'ast' and words['score'] == 0.0, json.dumps(words))
java = nfr_pattern_report('public class S { // retry\n  Retry retry = Retry.of("x"); }', ['RetryWithBackoff'])
check('other languages keep the pattern check (comments removed)', java['method'] == 'pattern' and java['score'] == 1.0)

# ---- 2.4 aidlc-build reports whether a failure can be resent --------------------------------------
from a2c_cli import build

request = json.loads((Path(__file__).resolve().parent / 'examples/requests/agents-python.json').read_text())
request['harness']['generator_type'] = 'e2a_abstract'      # a2c_sdlc.enabled needs an inherited generator
with tempfile.TemporaryDirectory() as tmp:
    report = build(request, Path(tmp))
check('an invalid build is reported as not retryable, with what to do next',
      not report['success'] and report['phase_reached'] == 'REJECTED_INVALID' and report['retryable'] is False
      and 'fails the same way every time' in report['next_step'], json.dumps(report, default=str)[:600])

print(f'\n{passed} checks passed')
