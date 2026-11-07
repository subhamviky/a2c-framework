"""a2c_concurrency.py — concurrency primitives for G2C generators, the P0
bootstrapper and DeveloperPlatformWorkflow (G2C Framework Reference
Section 17, P0 Framework Reference Section 4.1, A2C Section 3.5).

Standalone on purpose: this repository does not ship e2a_base.py, so the
types below mirror E2A's contracts (ClaimStatus, ClaimResult, Deadline and
the BaseIdempotencyStore claim/complete/fail surface) value-for-value. Any
object with that surface works as config['idempotency_store'] — including
E2A's own InMemoryIdempotencyStore or a managed-store adapter.

What is here:
  * InMemoryClaimStore      — reference claim store (single process, tests).
  * ClaimGuard              — one claim per key, settled on every exit path.
  * Deadline / check_deadline / DeadlineExceeded — remaining-time budget.
  * InferenceRejected       — typed, retryable model-call rejection.
  * InMemoryArtifactRegistry, register_artifact, release_artifact —
    compare-and-set ownership of shared abstract-class artifacts.
  * fingerprint_of, status_of, run_coro_sync — small helpers.

Nothing here has been validated against a live distributed store, a live
inference gateway or production load.
"""
import asyncio
import copy
import hashlib
import inspect
import json
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional

__all__ = [
    'ClaimStatus', 'ClaimResult', 'InMemoryClaimStore', 'ClaimGuard',
    'Deadline', 'DeadlineExceeded', 'check_deadline', 'InferenceRejected',
    'InMemoryArtifactRegistry', 'register_artifact', 'release_artifact',
    'fingerprint_of', 'status_of', 'run_coro_sync', 'DETERMINISTIC_ERRORS',
]

# Deterministic failures (validation / policy / type errors) are never retried.
DETERMINISTIC_ERRORS = (ValueError, TypeError, PermissionError)


# ─────────────────────────────────────────────────────────────── claim types
class ClaimStatus(str, Enum):
    """Same values as e2a_base.ClaimStatus."""
    CLAIMED = 'CLAIMED'                      # caller owns the work
    IN_PROGRESS = 'IN_PROGRESS'              # another owner holds an unexpired claim
    REPLAY = 'REPLAY'                        # already SUCCEEDED; result is the stored one
    CONFLICT = 'CONFLICT'                    # same key, different request fingerprint
    RECOVERY_REQUIRED = 'RECOVERY_REQUIRED'  # lease expired / outcome UNKNOWN -> reconcile
    FAILED_FINAL = 'FAILED_FINAL'            # deterministic failure; never re-executed


@dataclass
class ClaimResult:
    status: ClaimStatus
    result: Optional[Dict[str, Any]] = None
    owner: Optional[str] = None


def status_of(claim) -> str:
    """'CLAIMED' | 'REPLAY' | ... for this module's ClaimResult or E2A's."""
    st = getattr(claim, 'status', claim)
    return str(getattr(st, 'value', st))


class InMemoryClaimStore:
    """Reference claim store. State per (tenant, key):
        ABSENT -> IN_PROGRESS(owner, lease) -> SUCCEEDED(result)
                                            -> FAILED_RETRYABLE | FAILED_FINAL
                                            -> UNKNOWN (needs reconciliation)
    claim() is one atomic step (a lock stands in for a store's conditional
    write). Behaviour matches e2a_inmemory_adapters.InMemoryIdempotencyStore."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._lock, self._rec, self._clock = threading.Lock(), {}, clock

    @staticmethod
    def _k(key, tenant_id):
        return f"{tenant_id or '-'}:{key}"

    def claim(self, idempotency_key, config=None, **kw) -> ClaimResult:
        k, now = self._k(idempotency_key, kw.get('tenant_id')), self._clock()
        fp, owner = kw.get('fingerprint'), kw.get('owner') or str(uuid.uuid4())
        lease = float(kw.get('lease_seconds') or 300)
        ttl = kw.get('ttl_seconds')
        with self._lock:
            r = self._rec.get(k)
            if r and r.get('expires_at') and now >= r['expires_at']:
                r = None                       # explicit expiry field, not store-TTL timing
            if r is None or r['state'] == 'FAILED_RETRYABLE':
                self._rec[k] = {'state': 'IN_PROGRESS', 'owner': owner, 'lease_until': now + lease,
                                'fp': fp, 'result': None,
                                'expires_at': (now + float(ttl)) if ttl else None}
                return ClaimResult(ClaimStatus.CLAIMED, owner=owner)
            if fp is not None and r['fp'] is not None and fp != r['fp']:
                return ClaimResult(ClaimStatus.CONFLICT)
            if r['state'] == 'SUCCEEDED':
                return ClaimResult(ClaimStatus.REPLAY, result=copy.deepcopy(r['result']))
            if r['state'] == 'FAILED_FINAL':
                return ClaimResult(ClaimStatus.FAILED_FINAL)
            expired = r['state'] == 'IN_PROGRESS' and now >= r['lease_until']
            if r['state'] == 'UNKNOWN' or expired:
                if kw.get('recover'):          # a reconciler takes over, then confirms truth
                    r.update(state='IN_PROGRESS', owner=owner, lease_until=now + lease)
                    return ClaimResult(ClaimStatus.CLAIMED, owner=owner)
                return ClaimResult(ClaimStatus.RECOVERY_REQUIRED)
            return ClaimResult(ClaimStatus.IN_PROGRESS, owner=r['owner'])

    def _owned(self, k, owner):
        r = self._rec.get(k)
        return r if (r and r['state'] == 'IN_PROGRESS' and r['owner'] == owner) else None

    def complete(self, idempotency_key, result, config=None, **kw) -> bool:
        k = self._k(idempotency_key, kw.get('tenant_id'))
        with self._lock:
            r = self._owned(k, kw.get('owner'))
            if not r:
                return False                   # stale owner: its lease was taken over
            r.update(state='SUCCEEDED', result=result)
            return True

    def fail(self, idempotency_key, retryable=True, config=None, **kw) -> bool:
        k = self._k(idempotency_key, kw.get('tenant_id'))
        with self._lock:
            r = self._owned(k, kw.get('owner'))
            if not r:
                return False
            if str(getattr(kw.get('outcome'), 'value', kw.get('outcome'))) == 'UNKNOWN':
                r['state'] = 'UNKNOWN'
            else:
                r['state'] = 'FAILED_RETRYABLE' if retryable else 'FAILED_FINAL'
            return True

    # test helpers
    def state_of(self, key, tenant_id=None) -> Optional[str]:
        r = self._rec.get(self._k(key, tenant_id))
        return r['state'] if r else None

    def expire_lease(self, key, tenant_id=None) -> None:
        with self._lock:
            r = self._rec.get(self._k(key, tenant_id))
            if r:
                r['lease_until'] = self._clock() - 1


class ClaimGuard:
    """One atomic claim on (tenant, key), settled exactly once.

    Without a store the guard is a no-op owner: the caller proceeds and the
    guarantee is single-process (the legacy behaviour). With a store:
    acquire() -> CLAIMED makes this guard the owner; any other status is
    returned to the caller as a typed outcome and nothing is executed."""

    def __init__(self, store, key: str, tenant_id: Optional[str], fingerprint: Optional[str],
                 config: Optional[dict] = None, lease_seconds: float = 300.0,
                 ttl_seconds: Optional[float] = None):
        self.store, self.key, self.tenant_id = store, key, tenant_id
        self.fingerprint, self.config = fingerprint, config or {}
        self.lease_seconds, self.ttl_seconds = lease_seconds, ttl_seconds
        self.owner = str(uuid.uuid4())
        self.owned = False
        self.settled = False
        self.claim = None

    def acquire(self):
        if self.store is None:
            self.owned = True
            self.claim = ClaimResult(ClaimStatus.CLAIMED, owner=self.owner)
            return self.claim
        kw = dict(tenant_id=self.tenant_id, fingerprint=self.fingerprint, owner=self.owner,
                  lease_seconds=self.lease_seconds)
        if self.ttl_seconds:
            kw['ttl_seconds'] = self.ttl_seconds
        self.claim = self.store.claim(self.key, self.config, **kw)
        self.owned = status_of(self.claim) == 'CLAIMED'
        if not self.owned:
            self.settled = True                # nothing of ours to settle
        return self.claim

    def _kw(self, **extra):
        return dict(tenant_id=self.tenant_id, owner=self.owner, **extra)

    def succeed(self, result: dict) -> bool:
        if self.settled or not self.owned:
            return False
        self.settled = True
        # Store a deep copy: the caller keeps mutating its result (e.g. A2C
        # enriches a dev_request in place), and a replay must return what was
        # settled, not what the object became later.
        return True if self.store is None else bool(
            self.store.complete(self.key, copy.deepcopy(result), self.config, **self._kw()))

    def fail(self, retryable: bool = True) -> bool:
        if self.settled or not self.owned:
            return False
        self.settled = True
        return True if self.store is None else bool(
            self.store.fail(self.key, retryable, self.config, **self._kw()))

    def park_unknown(self) -> bool:
        """A failure after the first side effect: park for reconciliation."""
        if self.settled or not self.owned:
            return False
        self.settled = True
        return True if self.store is None else bool(
            self.store.fail(self.key, True, self.config, **self._kw(outcome='UNKNOWN')))

    def settle_exception(self, error: BaseException, side_effects_possible: bool) -> bool:
        """UNKNOWN if a side effect may have happened; FINAL for a
        deterministic error before any side effect; otherwise RETRYABLE
        (model rejection, deadline, cancellation, transient error)."""
        if side_effects_possible:
            return self.park_unknown()
        retryable = not isinstance(error, DETERMINISTIC_ERRORS) or isinstance(error, DeadlineExceeded)
        return self.fail(retryable=retryable)


# ─────────────────────────────────────────────────────────────── deadlines
class DeadlineExceeded(RuntimeError):
    """The request's remaining deadline reached zero."""


class InferenceRejected(RuntimeError):
    """The inference gateway rejected or failed the call (capacity, quota,
    timeout, provider error). Always retryable; no side effect happened."""

    def __init__(self, message: str, error_type: str = 'InferenceRejected'):
        super().__init__(message)
        self.error_type = error_type


class Deadline:
    """Same API as e2a_base.Deadline: absolute on the monotonic clock,
    carried across a boundary as remaining milliseconds."""
    __slots__ = ('_at',)

    def __init__(self, at_monotonic: float):
        self._at = at_monotonic

    @classmethod
    def after(cls, seconds: float) -> 'Deadline':
        return cls(time.monotonic() + float(seconds))

    @classmethod
    def from_remaining_ms(cls, ms) -> 'Deadline':
        return cls.after(float(ms) / 1000.0)

    @classmethod
    def coerce(cls, value) -> Optional['Deadline']:
        if value is None or hasattr(value, 'remaining'):
            return value
        return cls.after(float(value))

    @classmethod
    def from_request(cls, request: dict, config: Optional[dict] = None) -> Optional['Deadline']:
        """request['deadline_ms'] (remaining ms) wins; else config['deadline']."""
        if (request or {}).get('deadline_ms') is not None:
            return cls.from_remaining_ms(request['deadline_ms'])
        return cls.coerce((config or {}).get('deadline'))

    def remaining(self) -> float:
        return max(0.0, self._at - time.monotonic())

    def expired(self) -> bool:
        return time.monotonic() >= self._at

    def bound(self, timeout: Optional[float]) -> float:
        rem = self.remaining()
        return rem if timeout is None else min(float(timeout), rem)

    def check(self, what: str = 'operation') -> None:
        if self.expired():
            raise DeadlineExceeded(f'request deadline exceeded before {what}')

    def to_remaining_ms(self) -> int:
        return int(self.remaining() * 1000)

    def __float__(self) -> float:
        """Remaining seconds, so e2a_base.Deadline.coerce() accepts this object."""
        return self.remaining()


def check_deadline(deadline: Optional[Deadline], what: str) -> None:
    if deadline is not None and deadline.expired():
        raise DeadlineExceeded(f'request deadline exceeded before {what}')


# ─────────────────────────────────────────────────── shared-artifact ownership
class InMemoryArtifactRegistry:
    """Versioned records {refs, creator, deleted}; compare_and_set() is the
    atomic primitive. A managed store binds the same two calls to a
    conditional write (e.g. E2A BaseTransactionalStore.put_if_version)."""

    def __init__(self):
        self._lock, self._rec = threading.Lock(), {}

    def get(self, path: str) -> Optional[dict]:
        with self._lock:
            cur = self._rec.get(path)
            return None if cur is None else dict(cur[0], refs=list(cur[0]['refs']))

    def get_versioned(self, path: str):
        with self._lock:
            cur = self._rec.get(path)
            return None if cur is None else (dict(cur[0], refs=list(cur[0]['refs'])), cur[1])

    def compare_and_set(self, path: str, record: dict, expected_version: Optional[int]) -> bool:
        with self._lock:
            cur = self._rec.get(path)
            ver = cur[1] if cur else None
            if ver != expected_version:
                return False
            self._rec[path] = (dict(record, refs=list(record['refs'])), (ver or 0) + 1)
            return True


def register_artifact(registry, path: str, generator_key: str, created_fresh: bool,
                      max_attempts: int = 16) -> dict:
    """Add generator_key to the artifact's references. The first registrant
    of a freshly generated artifact becomes its creator; an artifact loaded
    from 'path' or 'package' has no creator and is never removable."""
    for _ in range(max_attempts):
        cur = registry.get_versioned(path)
        if cur is None or cur[0].get('deleted'):
            rec = {'refs': [generator_key], 'creator': generator_key if created_fresh else None,
                   'deleted': False}
            ver = cur[1] if cur else None
        else:
            rec, ver = cur
            if generator_key in rec['refs']:
                return rec
            rec['refs'].append(generator_key)
            if rec.get('creator') is None and created_fresh and not rec['refs'][:-1]:
                rec['creator'] = generator_key
        if registry.compare_and_set(path, rec, ver):
            return rec
    raise RuntimeError(f'artifact registry contention on {path}')


def release_artifact(registry, path: str, generator_key: str, max_attempts: int = 16) -> bool:
    """Remove generator_key's reference. Returns True only for the one
    caller allowed to delete the file: the creator, releasing the last
    reference, of an artifact not already deleted."""
    for _ in range(max_attempts):
        cur = registry.get_versioned(path)
        if cur is None:
            return False
        rec, ver = cur
        if rec.get('deleted') or generator_key not in rec['refs']:
            return False
        rec['refs'].remove(generator_key)
        may_delete = not rec['refs'] and rec.get('creator') == generator_key
        if may_delete:
            rec['deleted'] = True
        if registry.compare_and_set(path, rec, ver):
            return may_delete
    raise RuntimeError(f'artifact registry contention on {path}')


# ─────────────────────────────────────────────────────────────── helpers
_VOLATILE = {'deadline_ms', 'deadline', 'trace_id', 'correlation_id', 'errors',
             'scaffold_key', 'scaffold_plan', 'scaffolded_files',
             'generator_key', 'generated_files', 'critic_report', 'status', 'replayed'}


def fingerprint_of(request: dict, exclude=()) -> str:
    """Stable hash of a request's business content. The same key with a
    different fingerprint is a CONFLICT, never a replay."""
    skip = _VOLATILE | set(exclude)
    body = {k: v for k, v in (request or {}).items() if k not in skip}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


_bridge_lock = threading.Lock()
_bridge_loop: Optional[asyncio.AbstractEventLoop] = None


def _loop() -> asyncio.AbstractEventLoop:
    global _bridge_loop
    with _bridge_lock:
        if _bridge_loop is None or _bridge_loop.is_closed():
            _bridge_loop = asyncio.new_event_loop()
            threading.Thread(target=_bridge_loop.run_forever, name='a2c-bridge-loop',
                             daemon=True).start()
        return _bridge_loop


def run_coro_sync(value, timeout: Optional[float] = None):
    """Run an awaitable from synchronous code on one process-wide loop (so a
    gateway's semaphores and token bucket stay bound to a single loop,
    whatever thread calls). A plain value is returned unchanged."""
    if not inspect.isawaitable(value):
        return value
    fut = asyncio.run_coroutine_threadsafe(_ensure_coro(value), _loop())
    return fut.result(timeout)


async def _ensure_coro(aw):
    return await aw
