"""Tests del motor de ejecución con fakes: sin red, sin Postgres, sin Redis."""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.engine.loop import execute_run
from app.llm.toolcalling import StepOutcome, ToolCallRequest
from app.models import TraceStep
from app.tools.base import Tool, ToolContext, ToolError


class FakeAgent(SimpleNamespace):
    pass


class FakeDB:
    """Sesión async mínima: captura adds y sirve run/agent por orden de consulta."""

    def __init__(self, run, agent):
        self._results = [run, agent]
        self.added: list = []
        self.commits = 0

    async def scalar(self, _query):
        return self._results.pop(0) if self._results else None

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


class EchoTool(Tool):
    name = "echo"
    description = "eco"
    input_schema = {"type": "object", "properties": {"text": {"type": "string"}}}
    timeout_seconds = 5

    async def run(self, args: dict, ctx: ToolContext) -> str:
        return f"eco:{args.get('text', '')}"


class FailTool(Tool):
    name = "boom"
    description = "siempre falla"
    input_schema = {"type": "object", "properties": {}}
    timeout_seconds = 5

    async def run(self, args: dict, ctx: ToolContext) -> str:
        raise ToolError("explotó a propósito")


class ScriptedSession:
    """ToolCallingSession falsa que sigue un guion de StepOutcomes."""

    script: list[StepOutcome] = []
    instances: list = []

    def __init__(self, provider, model, system_prompt, tools):
        self.provider = provider
        self.model = model
        self._script = list(type(self).script)
        self.tool_results_received: list = []
        type(self).instances.append(self)

    async def send_user(self, content: str) -> StepOutcome:
        return self._script.pop(0)

    async def send_tool_results(self, results) -> StepOutcome:
        self.tool_results_received.append(results)
        return self._script.pop(0)

    def export_messages(self):
        return [{"role": "system", "content": "fake"}]


def make_run_agent(**agent_overrides):
    run = SimpleNamespace(
        id=uuid.uuid4(), agent_id=uuid.uuid4(), team_id=None, goal="objetivo de prueba",
        status="queued", checkpoint=None, error=None,
        total_cost_usd=0.0, total_tokens=0, started_at=None, finished_at=None,
    )
    defaults = dict(
        id=run.agent_id, name="Tester", model_provider="anthropic",
        model_name="claude-opus-4-8", system_prompt="Eres útil.",
        max_steps=10, max_cost_usd=1.0, temperature=None,
    )
    agent = FakeAgent(**{**defaults, **agent_overrides})
    return run, agent


def run_engine(run, agent, script, tools=None):
    events: list[dict] = []

    async def publish(run_id, event):
        events.append(event)

    db = FakeDB(run, agent)

    @asynccontextmanager
    async def factory():
        yield db

    ScriptedSession.script = script
    ScriptedSession.instances = []
    return execute_run(
        run.id, session_factory=factory, session_cls=ScriptedSession,
        tools=tools if tools is not None else [EchoTool(), FailTool()],
        publish=publish,
    ), db, events


async def test_happy_path_tool_then_final():
    run, agent = make_run_agent()
    script = [
        StepOutcome(text="", tool_calls=[ToolCallRequest("c1", "echo", {"text": "hola"})],
                    tokens_in=100, tokens_out=50, cost_usd=0.01),
        StepOutcome(text="Respuesta final", tokens_in=120, tokens_out=30, cost_usd=0.01),
    ]
    coro, db, events = run_engine(run, agent, script)
    await coro

    assert run.status == "completed"
    assert run.checkpoint["final_answer"] == "Respuesta final"
    assert run.total_tokens == 300
    kinds = [s.kind for s in db.added if isinstance(s, TraceStep)]
    assert kinds == ["llm_call", "tool_call", "llm_call"]
    # La herramienta se ejecutó de verdad y su resultado volvió a la sesión
    session = ScriptedSession.instances[0]
    assert session.tool_results_received[0][0] == ("c1", "eco:hola", False)
    assert events[-1]["type"] == "run_finished"
    assert events[-1]["status"] == "completed"


async def test_tool_error_recovers():
    run, agent = make_run_agent()
    script = [
        StepOutcome(text="", tool_calls=[ToolCallRequest("c1", "boom", {})]),
        StepOutcome(text="Me recuperé"),
    ]
    coro, db, events = run_engine(run, agent, script)
    await coro

    assert run.status == "completed"
    session = ScriptedSession.instances[0]
    call_id, output, is_error = session.tool_results_received[0][0]
    assert is_error is True
    assert "explotó a propósito" in output


async def test_budget_exhausted_clean_stop():
    run, agent = make_run_agent(max_cost_usd=0.005)
    script = [
        StepOutcome(text="pensando", tool_calls=[ToolCallRequest("c1", "echo", {"text": "x"})],
                    cost_usd=0.01),
        StepOutcome(text="no debería llegar aquí"),
    ]
    coro, db, events = run_engine(run, agent, script)
    await coro

    assert run.status == "completed"
    assert run.checkpoint["partial"] is True
    assert "presupuesto" in run.checkpoint["reason"]


async def test_max_steps_reached():
    run, agent = make_run_agent(max_steps=1)
    script = [
        StepOutcome(text="", tool_calls=[ToolCallRequest("c1", "echo", {"text": "x"})]),
    ]
    coro, db, events = run_engine(run, agent, script)
    await coro

    assert run.status == "failed"
    assert "max_steps" in run.error


async def test_unknown_tool_reported_as_error():
    run, agent = make_run_agent()
    script = [
        StepOutcome(text="", tool_calls=[ToolCallRequest("c1", "inexistente", {})]),
        StepOutcome(text="fin"),
    ]
    coro, db, events = run_engine(run, agent, script, tools=[EchoTool()])
    await coro

    session = ScriptedSession.instances[0]
    _, output, is_error = session.tool_results_received[0][0]
    assert is_error is True
    assert "desconocida" in output


async def test_terminal_run_not_reexecuted():
    run, agent = make_run_agent()
    run.status = "cancelled"
    coro, db, events = run_engine(run, agent, [])
    await coro
    assert run.status == "cancelled"
    assert events == []
