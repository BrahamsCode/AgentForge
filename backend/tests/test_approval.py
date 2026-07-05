"""Test del gate de aprobación en el motor (Fase 4 / O5), con fakes y sin sleeps largos."""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.engine.loop import execute_run
from app.llm.toolcalling import StepOutcome, ToolCallRequest
from app.models import Approval, TraceStep
from app.tools.base import Tool, ToolContext


class DangerousTool(Tool):
    name = "deploy"
    description = "despliega"
    input_schema = {"type": "object", "properties": {}}
    risk_level = "dangerous"
    timeout_seconds = 5

    async def run(self, args: dict, ctx: ToolContext) -> str:
        return "desplegado"


class FakeDB:
    def __init__(self, run, agent, on_approval_created):
        self._results = [run, agent]
        self.added: list = []
        self.commits = 0
        self._on_approval_created = on_approval_created

    async def scalar(self, _query):
        return self._results.pop(0) if self._results else None

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, Approval):
            if obj.id is None:
                obj.id = uuid.uuid4()
            self._on_approval_created(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        pass


class ScriptedSession:
    script: list = []

    def __init__(self, provider, model, system_prompt, tools):
        self.provider = provider
        self.model = model
        self._script = list(type(self).script)
        self.received = []

    async def send_user(self, content):
        return self._script.pop(0)

    async def send_tool_results(self, results):
        self.received.append(results)
        return self._script.pop(0)

    def export_messages(self):
        return []


def _world():
    run = SimpleNamespace(
        id=uuid.uuid4(), agent_id=uuid.uuid4(), team_id=None, goal="despliega la app",
        status="queued", checkpoint=None, error=None,
        total_cost_usd=0.0, total_tokens=0, started_at=None, finished_at=None,
    )
    agent = SimpleNamespace(
        id=run.agent_id, name="Ops", model_provider="anthropic", model_name="claude-opus-4-8",
        system_prompt="", max_steps=10, max_cost_usd=5.0, temperature=None,
    )
    return run, agent


async def _run(run, agent, decision: str):
    """decision: lo que 'el humano' pone en la Approval en cuanto se crea."""
    settings = get_settings()
    settings.approval_poll_seconds = 0.01  # test rápido
    settings.approval_timeout_seconds = 5

    events: list[dict] = []

    async def publish(run_id, event):
        events.append(event)

    def on_created(approval):
        approval.status = decision  # el humano decide de inmediato

    db = FakeDB(run, agent, on_created)

    @asynccontextmanager
    async def factory():
        yield db

    ScriptedSession.script = [
        StepOutcome(text="", tool_calls=[ToolCallRequest("c1", "deploy", {})]),
        StepOutcome(text="listo"),
    ]
    await execute_run(
        run.id, session_factory=factory, session_cls=ScriptedSession,
        tools=[DangerousTool()], publish=publish,
    )
    return db, events


async def test_dangerous_tool_pauses_and_runs_on_approval():
    run, agent = _world()
    db, events = await _run(run, agent, "approved")

    # Se creó la aprobación y se emitió el evento de pausa
    assert any(isinstance(o, Approval) for o in db.added)
    assert any(e["type"] == "approval_required" for e in events)
    assert any(e.get("decision") == "approved" for e in events if e["type"] == "approval_decided")

    # La herramienta se ejecutó (resultado real, no rechazo)
    session = ScriptedSession.script  # consumido; usamos el resultado vía trace
    tool_steps = [s for s in db.added if isinstance(s, TraceStep) and s.kind == "tool_call"]
    assert tool_steps[0].output == {"result": "desplegado"}
    assert run.status == "completed"


async def test_dangerous_tool_rejected_returns_denial():
    run, agent = _world()
    db, events = await _run(run, agent, "rejected")

    tool_steps = [s for s in db.added if isinstance(s, TraceStep) and s.kind == "tool_call"]
    assert "rechazada" in tool_steps[0].output["error"]
    assert run.status == "completed"  # el run sigue; el LLM recibió el rechazo
