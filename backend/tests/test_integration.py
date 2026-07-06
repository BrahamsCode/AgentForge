"""Prueba de integración del pipeline real: cola → worker → motor → eventos.

A diferencia de test_engine/test_queue (que parchean execute_run o la sesión),
aquí corren las implementaciones REALES de bus.enqueue_run, worker.worker_loop
y engine.execute_run juntas, contra fakeredis y una BD en memoria. Solo se
sustituye el LLM (stub) para no tocar la red.
"""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import fakeredis.aioredis
import pytest

from app import db as db_module
from app.engine import loop as loop_module
from app.llm.toolcalling import StepOutcome
from app.models import Run, TraceStep
from app.queue import bus, redis_client, worker


class InMemoryDB:
    """Sesión async mínima; sirve Run y Agent por orden (como los pide execute_run)."""

    def __init__(self, run, agent):
        self._scalars = [run, agent]
        self.rows: list = []

    async def scalar(self, _query):
        return self._scalars.pop(0) if self._scalars else None

    def add(self, obj):
        self.rows.append(obj)

    async def commit(self):
        pass

    async def refresh(self, _obj):
        pass


class StubSession:
    """LLM stub: primero razona sin herramientas y entrega la respuesta final."""

    def __init__(self, provider, model, system_prompt, tools):
        self.provider = provider
        self.model = model

    async def send_user(self, content):
        return StepOutcome(
            text="Respuesta final integrada", tokens_in=100, tokens_out=40, cost_usd=0.005
        )

    async def send_tool_results(self, results):
        return StepOutcome(text="fin")

    def export_messages(self):
        return [{"role": "user", "content": "objetivo"}]


@pytest.fixture
def fake_redis(monkeypatch):
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_client, "_redis", r)
    return r


async def test_full_pipeline_queue_worker_engine_events(fake_redis, monkeypatch):
    run_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    run = SimpleNamespace(
        id=run_id, agent_id=agent_id, team_id=None, goal="prueba de integración",
        status="queued", checkpoint=None, error=None, parent_run_id=None,
        total_cost_usd=0.0, total_tokens=0, started_at=None, finished_at=None,
    )
    agent = SimpleNamespace(
        id=agent_id, name="Integrador", model_provider="anthropic",
        model_name="claude-opus-4-8", system_prompt="Eres útil.",
        max_steps=10, max_cost_usd=1.0, temperature=None,
    )
    store = InMemoryDB(run, agent)

    @asynccontextmanager
    async def fake_session():
        yield store

    # Parchea la BD real (SessionLocal) y el LLM real; el resto es genuino.
    monkeypatch.setattr(db_module, "SessionLocal", fake_session)
    monkeypatch.setattr(loop_module, "ToolCallingSession", StubSession)

    # 1) La API encolaría así:
    await bus.enqueue_run(str(run_id))

    # 2) El worker real consume y ejecuta el motor real:
    await worker.ensure_group()
    await worker.worker_loop("integ", mark_failed=lambda *a: None, max_iterations=1)

    # 3) El run terminó correctamente y quedó traza:
    assert run.status == "completed"
    assert run.checkpoint["final_answer"] == "Respuesta final integrada"
    assert run.total_tokens == 140
    assert any(isinstance(r, TraceStep) and r.kind == "llm_call" for r in store.rows)

    # 4) Los eventos llegaron al stream real de Redis (lo que consume el SSE):
    import json

    key = bus.EVENTS_KEY_TEMPLATE.format(run_id=str(run_id))
    entries = await fake_redis.xrange(key)
    types = [json.loads(f["data"])["type"] for _id, f in entries]
    assert "step" in types
    assert types[-1] == "run_finished"

    # 5) El mensaje de la cola quedó reconocido (no pendiente):
    pending = await fake_redis.xpending(bus.RUNS_STREAM, bus.RUNS_GROUP)
    assert pending["pending"] == 0
