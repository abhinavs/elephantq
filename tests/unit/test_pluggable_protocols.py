"""
Soniq exposes three pluggable extension points in 0.0.2:

- `RetryPolicy` (`soniq.core.retry`)
- `Serializer` (`soniq.utils.serialization`)
- `LogSink` is reserved for the dashboard logging path; tests live with
  `features/logging`.

Each ships a default implementation and a `Soniq(...)` constructor
parameter. These tests pin the contract.
"""

import pytest

from soniq import Soniq
from soniq.backends.memory import MemoryBackend
from soniq.core.processor import process_job_via_backend
from soniq.core.registry import JobRegistry
from soniq.core.retry import (
    DEFAULT_RETRY_POLICY,
    ExponentialBackoff,
    RetryPolicy,
)
from soniq.utils.serialization import (
    DEFAULT_SERIALIZER,
    JSONSerializer,
    Serializer,
)


def test_default_retry_policy_implements_protocol():
    assert isinstance(DEFAULT_RETRY_POLICY, RetryPolicy)
    assert isinstance(ExponentialBackoff(), RetryPolicy)


def test_default_serializer_implements_protocol():
    assert isinstance(DEFAULT_SERIALIZER, Serializer)
    assert isinstance(JSONSerializer(), Serializer)


def test_json_serializer_round_trip_dict():
    s = JSONSerializer()
    raw = s.dumps({"x": 1, "y": "hi"})
    assert s.loads(raw) == {"x": 1, "y": "hi"}


def test_json_serializer_idempotent_on_dict():
    """Backends often pass already-decoded dicts back into loads(); the
    default must accept that without trying to re-parse."""
    s = JSONSerializer()
    assert s.loads({"already": "decoded"}) == {"already": "decoded"}
    assert s.loads(None) is None


def test_soniq_accepts_custom_retry_policy():
    class _Policy:
        def delay_for(self, *, attempt, job_meta, exc):
            return 0.1

    app = Soniq(
        database_url="postgresql://user:pass@localhost/test", retry_policy=_Policy()
    )
    assert app._retry_policy.delay_for(attempt=1, job_meta={}, exc=Exception()) == 0.1


def test_soniq_accepts_custom_serializer():
    class _Serializer:
        def dumps(self, value):
            return "stub"

        def loads(self, raw):
            return {"stub": True}

    app = Soniq(
        database_url="postgresql://user:pass@localhost/test", serializer=_Serializer()
    )
    assert app._serializer.dumps({}) == "stub"


@pytest.mark.asyncio
async def test_retry_policy_can_short_circuit_to_dead_letter():
    """A RetryPolicy that returns None should dead-letter the job
    immediately, even if there's still retry budget remaining."""

    class _NoRetry:
        def delay_for(self, *, attempt, job_meta, exc):
            return None

    backend = MemoryBackend()
    await backend.initialize()
    registry = JobRegistry()

    async def always_fails():
        raise RuntimeError("nope")

    registry.register_job(always_fails, max_retries=5)
    job_name = f"{always_fails.__module__}.{always_fails.__name__}"

    await backend.create_job(
        job_id="dl-policy",
        job_name=job_name,
        args={},
        args_hash=None,
        max_attempts=6,
        priority=100,
        queue="default",
        unique=False,
        dedup_key=None,
        scheduled_at=None,
    )

    await process_job_via_backend(
        backend=backend,
        job_registry=registry,
        queues=["default"],
        retry_policy=_NoRetry(),
    )

    job = await backend.get_job("dl-policy")
    assert job["status"] == "dead_letter"
    assert "Retry policy declined" in job["last_error"]
