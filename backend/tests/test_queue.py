"""Tests de la cola con fakeredis: sin Redis real, sin Postgres."""

import json
import uuid
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from app.queue import bus, redis_client, worker


@pytest.fixture
def fake_redis(monkeypatch):
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_client, "_redis", r)
    return r


async def test_enqueue_and_consume(fake_redis):
    run_id = uuid.uuid4()
    await bus.enqueue_run(str(run_id))
    await worker.ensure_group()

    executed: list[uuid.UUID] = []

    async def fake_execute(rid):
        executed.append(rid)

    with patch("app.engine.loop.execute_run", side_effect=fake_execute):
        await worker.worker_loop("w1", mark_failed=AsyncMock(), max_iterations=1)

    assert executed == [run_id]
    pending = await fake_redis.xpending(bus.RUNS_STREAM, bus.RUNS_GROUP)
    assert pending["pending"] == 0


async def test_publish_event_format_and_ttl(fake_redis):
    await bus.publish_event("run-123", {"type": "step", "step": 1})
    key = bus.EVENTS_KEY_TEMPLATE.format(run_id="run-123")

    entries = await fake_redis.xrange(key)
    assert len(entries) == 1
    _id, fields = entries[0]
    assert json.loads(fields["data"]) == {"type": "step", "step": 1}
    assert await fake_redis.ttl(key) > 0


async def test_failed_execute_still_acked_and_marked(fake_redis):
    run_id = uuid.uuid4()
    await bus.enqueue_run(str(run_id))
    await worker.ensure_group()

    mark_failed = AsyncMock()
    with patch("app.engine.loop.execute_run", side_effect=RuntimeError("proveedor caído")):
        await worker.worker_loop("w1", mark_failed=mark_failed, max_iterations=1)

    mark_failed.assert_awaited_once()
    assert mark_failed.await_args.args[0] == run_id
    assert "proveedor caído" in mark_failed.await_args.args[1]
    pending = await fake_redis.xpending(bus.RUNS_STREAM, bus.RUNS_GROUP)
    assert pending["pending"] == 0


async def test_invalid_run_id_acked(fake_redis):
    await fake_redis.xadd(bus.RUNS_STREAM, {"run_id": "no-es-uuid"})
    await worker.ensure_group()

    with patch("app.engine.loop.execute_run") as fake_execute:
        await worker.worker_loop("w1", mark_failed=AsyncMock(), max_iterations=1)

    fake_execute.assert_not_called()
    pending = await fake_redis.xpending(bus.RUNS_STREAM, bus.RUNS_GROUP)
    assert pending["pending"] == 0


async def test_ensure_group_idempotent(fake_redis):
    await worker.ensure_group()
    await worker.ensure_group()  # BUSYGROUP ignorado
