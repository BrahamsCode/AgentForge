"""Tests del orquestador multi-agente con fakes: sin red, BD ni Redis reales."""

import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.engine.orchestrator import _parse_plan, execute_team_run
from app.llm.toolcalling import StepOutcome, ToolCallRequest
from app.models import Task, TraceStep
from app.tools.base import Tool, ToolContext


class EchoTool(Tool):
    name = "echo"
    description = "eco"
    input_schema = {"type": "object", "properties": {"text": {"type": "string"}}}
    timeout_seconds = 5

    async def run(self, args: dict, ctx: ToolContext) -> str:
        return f"eco:{args.get('text', '')}"


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return list(self._rows)


class FakeDB:
    """Responde scalars por orden y execute() según la consulta (tasks/members)."""

    def __init__(self, scalars_queue, members_rows):
        self._scalars = list(scalars_queue)
        self._members_rows = members_rows
        self.added: list = []
        self.commits = 0

    async def scalar(self, _query):
        return self._scalars.pop(0) if self._scalars else None

    async def execute(self, query):
        text = str(query)
        if "team_members" in text:
            return FakeResult(self._members_rows)
        if "tasks" in text:
            return FakeResult([t for t in self.added if isinstance(t, Task)])
        return FakeResult([])

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, Task) and obj.id is None:
            obj.id = uuid.uuid4()

    async def commit(self):
        self.commits += 1


class ScriptedSession:
    """Guion global compartido: cada instancia consume del mismo guion por rol.

    El guion se indexa por el primer fragmento del system prompt para separar
    planner / sintetizador / miembros.
    """

    scripts: dict[str, list[StepOutcome]] = {}

    def __init__(self, provider, model, system_prompt, tools):
        self.provider = provider
        self.model = model
        self.system_prompt = system_prompt
        self.tools = tools
        self._key = next(
            (k for k in type(self).scripts if k in system_prompt), "default"
        )

    async def send_user(self, content: str) -> StepOutcome:
        return type(self).scripts[self._key].pop(0)

    async def send_tool_results(self, results) -> StepOutcome:
        return type(self).scripts[self._key].pop(0)

    def export_messages(self):
        return []


def make_world():
    """Equipo: orquestador + 2 miembros (researcher, writer)."""
    orchestrator = SimpleNamespace(
        id=uuid.uuid4(), name="Orquestador", role="orchestrator",
        model_provider="anthropic", model_name="claude-opus-4-8",
        system_prompt="ORQ", max_steps=10, max_cost_usd=5.0,
    )
    researcher = SimpleNamespace(
        id=uuid.uuid4(), name="Researcher", role="research",
        model_provider="anthropic", model_name="claude-haiku-4-5",
        system_prompt="RESEARCHER", max_steps=5, max_cost_usd=1.0,
    )
    writer = SimpleNamespace(
        id=uuid.uuid4(), name="Writer", role="writing",
        model_provider="anthropic", model_name="claude-sonnet-5",
        system_prompt="WRITER", max_steps=5, max_cost_usd=1.0,
    )
    team = SimpleNamespace(id=uuid.uuid4(), orchestrator_agent_id=orchestrator.id)
    run = SimpleNamespace(
        id=uuid.uuid4(), agent_id=None, team_id=team.id, goal="informe de mercado",
        status="queued", checkpoint=None, error=None,
        total_cost_usd=0.0, total_tokens=0, started_at=None, finished_at=None,
    )
    return run, team, orchestrator, researcher, writer


async def run_orchestrator(run, team, orchestrator, members, scripts):
    events: list[dict] = []

    async def publish(run_id, event):
        events.append(event)

    member_rows = [(m, m.role) for m in members]
    db = FakeDB([run, team, orchestrator], member_rows)

    @asynccontextmanager
    async def factory():
        yield db

    ScriptedSession.scripts = scripts
    await execute_team_run(
        run.id, session_factory=factory, session_cls=ScriptedSession,
        tools=[EchoTool()], publish=publish,
    )
    return db, events


def plan_json(tasks):
    return json.dumps({"tasks": tasks})


async def test_full_flow_plan_delegate_synthesize():
    run, team, orch, researcher, writer = make_world()
    scripts = {
        "ORQ": [
            # plan
            StepOutcome(text=plan_json([
                {"id": "t1", "description": "investiga fuentes", "agent": "researcher", "depends_on": []},
                {"id": "t2", "description": "investiga competidores", "agent": "researcher", "depends_on": []},
                {"id": "t3", "description": "redacta informe", "agent": "writer", "depends_on": ["t1", "t2"]},
            ]), tokens_in=100, tokens_out=50, cost_usd=0.02),
            # synthesize
            StepOutcome(text="INFORME FINAL", tokens_in=200, tokens_out=100, cost_usd=0.03),
        ],
        "RESEARCHER": [
            StepOutcome(text="hallazgos A", cost_usd=0.01),
            StepOutcome(text="hallazgos B", cost_usd=0.01),
        ],
        "WRITER": [
            # el writer usa una herramienta y luego termina
            StepOutcome(text="", tool_calls=[ToolCallRequest("c1", "echo", {"text": "borrador"})],
                        cost_usd=0.01),
            StepOutcome(text="informe redactado", cost_usd=0.01),
        ],
    }
    db, events = await run_orchestrator(run, team, orch, [researcher, writer], scripts)

    assert run.status == "completed"
    assert run.checkpoint["final_answer"] == "INFORME FINAL"
    assert run.checkpoint["orchestrator"]["phase"] == "done"

    tasks = [t for t in db.added if isinstance(t, Task)]
    assert len(tasks) == 3
    assert all(t.status == "completed" for t in tasks)
    # El writer dependía de t1 y t2: su resultado está y usó la herramienta
    writer_task = next(t for t in tasks if t.agent_id == writer.id)
    assert writer_task.result["answer"] == "informe redactado"

    kinds = [s.kind for s in db.added if isinstance(s, TraceStep)]
    assert kinds.count("tool_call") == 1
    assert kinds.count("llm_call") >= 5  # plan + 2 research + 2 writer + síntesis
    assert events[-1] == {
        "type": "run_finished", "run_id": str(run.id), "status": "completed",
    }
    # Costos acumulados de todos los agentes
    assert run.total_cost_usd == pytest.approx(0.02 + 0.01 + 0.01 + 0.01 + 0.01 + 0.03)


async def test_failed_task_does_not_block_synthesis():
    run, team, orch, researcher, writer = make_world()
    scripts = {
        "ORQ": [
            StepOutcome(text=plan_json([
                {"id": "t1", "description": "tarea imposible", "agent": "researcher", "depends_on": []},
            ]), cost_usd=0.01),
            StepOutcome(text="informe con lagunas", cost_usd=0.01),
        ],
        # El researcher agota su guion → IndexError → tarea failed
        "RESEARCHER": [],
    }
    db, events = await run_orchestrator(run, team, orch, [researcher, writer], scripts)

    assert run.status == "completed"
    tasks = [t for t in db.added if isinstance(t, Task)]
    assert tasks[0].status == "failed"
    assert run.checkpoint["final_answer"] == "informe con lagunas"


async def test_missing_orchestrator_fails_run():
    run, team, orch, researcher, writer = make_world()
    team.orchestrator_agent_id = None
    events: list[dict] = []

    async def publish(run_id, event):
        events.append(event)

    db = FakeDB([run, team], [])

    @asynccontextmanager
    async def factory():
        yield db

    await execute_team_run(run.id, session_factory=factory, session_cls=ScriptedSession,
                           tools=[], publish=publish)
    assert run.status == "failed"
    assert events[-1]["status"] == "failed"


def test_parse_plan_robustness():
    members = {"researcher": object(), "writer": object()}
    # JSON envuelto en prosa
    text = 'Claro, este es el plan:\n{"tasks": [{"id": "a", "description": "x", "agent": "WRITER", "depends_on": []}]}\nListo.'
    plan = _parse_plan(text, members)
    assert plan[0]["agent"] == "writer"

    # Agente inexistente → fallback al primero; depends_on inválido → filtrado
    plan = _parse_plan(
        plan_json([
        {"id": "a", "description": "x", "agent": "nadie", "depends_on": ["zz"]},
        ]),
        members,
    )
    assert plan[0]["agent"] == "researcher"
    assert plan[0]["depends_on"] == []

    # Sin JSON → plan degradado de una tarea
    plan = _parse_plan("no puedo planificar", members)
    assert len(plan) == 1
    assert plan[0]["agent"] == "researcher"
