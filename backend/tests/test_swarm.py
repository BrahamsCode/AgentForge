"""Tests del modo swarm con fakes: sin red, BD ni Redis reales."""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

from app.engine.swarm import _parse_winner, execute_swarm_run
from app.llm.toolcalling import StepOutcome, ToolCallRequest
from app.models import TraceStep
from app.tools.base import Tool, ToolContext


class EchoTool(Tool):
    name = "echo"
    description = "eco"
    input_schema = {"type": "object", "properties": {"text": {"type": "string"}}}
    timeout_seconds = 5

    async def run(self, args: dict, ctx: ToolContext) -> str:
        return f"eco:{args.get('text', '')}"


class FakeDB:
    """Responde `scalar()` por orden [run, agent]; captura los objetos añadidos."""

    def __init__(self, scalars_queue):
        self._scalars = list(scalars_queue)
        self.added: list = []
        self.commits = 0

    async def scalar(self, _query):
        return self._scalars.pop(0) if self._scalars else None

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


class ScriptedSession:
    """Guion por rol: el juez (marcador "JUEZ" en el system prompt) usa su
    propio guion; cada candidato consume, en orden de construcción, el siguiente
    guion de `candidate_scripts` (los candidatos son idénticos, no se pueden
    distinguir por el system prompt)."""

    judge_script: list[StepOutcome] = []
    candidate_scripts: list[list[StepOutcome]] = []
    _cand_cursor = 0

    def __init__(self, provider, model, system_prompt, tools):
        self.provider = provider
        self.model = model
        self.system_prompt = system_prompt
        self.tools = tools
        if "JUEZ" in system_prompt:
            self._script = type(self).judge_script
        else:
            i = type(self)._cand_cursor
            type(self)._cand_cursor += 1
            self._script = type(self).candidate_scripts[i]

    async def send_user(self, content: str) -> StepOutcome:
        return self._script.pop(0)

    async def send_tool_results(self, results) -> StepOutcome:
        return self._script.pop(0)

    def export_messages(self):
        return []

    @classmethod
    def configure(cls, candidate_scripts, judge_script):
        cls.candidate_scripts = candidate_scripts
        cls.judge_script = judge_script
        cls._cand_cursor = 0


def make_world():
    agent = SimpleNamespace(
        id=uuid.uuid4(), name="Solver", role="solver",
        model_provider="anthropic", model_name="claude-opus-4-8",
        system_prompt="SOLVER", max_steps=5, max_cost_usd=5.0,
    )
    run = SimpleNamespace(
        id=uuid.uuid4(), agent_id=agent.id, team_id=None, goal="resuelve el acertijo",
        status="queued", checkpoint=None, error=None,
        total_cost_usd=0.0, total_tokens=0, started_at=None, finished_at=None,
    )
    return run, agent


async def run_swarm(run, agent, candidate_scripts, judge_script, n_candidates=3):
    events: list[dict] = []

    async def publish(run_id, event):
        events.append(event)

    db = FakeDB([run, agent])

    @asynccontextmanager
    async def factory():
        yield db

    ScriptedSession.configure(candidate_scripts, judge_script)
    await execute_swarm_run(
        run.id, session_factory=factory, session_cls=ScriptedSession,
        tools=[EchoTool()], publish=publish, n_candidates=n_candidates,
    )
    return db, events


async def test_swarm_judge_picks_candidate_2():
    run, agent = make_world()
    candidate_scripts = [
        # Candidato 0: usa la herramienta y luego responde.
        [
            StepOutcome(text="", tool_calls=[ToolCallRequest("c0", "echo", {"text": "idea"})],
                        cost_usd=0.01),
            StepOutcome(text="solución del candidato 0", cost_usd=0.01),
        ],
        # Candidato 1 (ganador): responde directo.
        [StepOutcome(text="solución del candidato 1", cost_usd=0.01)],
        # Candidato 2.
        [StepOutcome(text="solución del candidato 2", cost_usd=0.01)],
    ]
    judge_script = [StepOutcome(text="2 porque es la más completa", cost_usd=0.02)]

    db, events = await run_swarm(run, agent, candidate_scripts, judge_script)

    assert run.status == "completed"
    assert run.checkpoint["final_answer"] == "solución del candidato 1"
    assert run.checkpoint["swarm"]["winner"] == 1
    assert run.checkpoint["swarm"]["n"] == 3
    assert len(run.checkpoint["swarm"]["candidates"]) == 3

    kinds = [s.kind for s in db.added if isinstance(s, TraceStep)]
    assert kinds.count("tool_call") == 1  # el candidato 0 ejecutó la herramienta
    # 2 (cand0 llm) + 1 (cand1) + 1 (cand2) + 1 (juez) = 5 llm_call
    assert kinds.count("llm_call") == 5
    assert events[-1] == {
        "type": "run_finished", "run_id": str(run.id), "status": "completed",
    }


async def test_swarm_failed_candidate_does_not_abort():
    run, agent = make_world()
    candidate_scripts = [
        [StepOutcome(text="solución válida del candidato 0", cost_usd=0.01)],
        [],  # guion agotado → IndexError → candidato 1 falla
        [StepOutcome(text="solución válida del candidato 2", cost_usd=0.01)],
    ]
    # El juez intenta elegir el 2 (índice 1), que falló → igualmente se registra
    # su elección; comprobamos que el fallido queda etiquetado.
    judge_script = [StepOutcome(text="1 es la mejor", cost_usd=0.02)]

    db, events = await run_swarm(run, agent, candidate_scripts, judge_script)

    assert run.status == "completed"
    cands = run.checkpoint["swarm"]["candidates"]
    assert cands[1].startswith("[CANDIDATO FALLIDO]")
    # El juez eligió el candidato 1 (índice 0), que es válido.
    assert run.checkpoint["swarm"]["winner"] == 0
    assert run.checkpoint["final_answer"] == "solución válida del candidato 0"
    assert events[-1]["status"] == "completed"


async def test_swarm_judge_unparseable_falls_back_to_valid():
    run, agent = make_world()
    candidate_scripts = [
        [],  # candidato 0 falla
        [StepOutcome(text="corta", cost_usd=0.01)],
        [StepOutcome(text="una solución claramente más larga y detallada", cost_usd=0.01)],
    ]
    # El juez responde texto sin número → fallback: candidato no-fallido más largo.
    judge_script = [StepOutcome(text="no estoy seguro, ambas son buenas", cost_usd=0.02)]

    db, events = await run_swarm(run, agent, candidate_scripts, judge_script)

    assert run.status == "completed"
    assert run.checkpoint["swarm"]["winner"] == 2  # el más largo no-fallido
    assert run.checkpoint["final_answer"] == "una solución claramente más larga y detallada"


def test_parse_winner_robustness():
    cands = ["a", "bb", "ccc"]
    # Número válido dentro de rango.
    assert _parse_winner("elijo el 2, es mejor", 3, cands) == 1
    # Número fuera de rango → fallback al más largo.
    assert _parse_winner("99", 3, cands) == 2
    # Sin número → fallback al más largo.
    assert _parse_winner("ninguna clara", 3, cands) == 2
    # Con un fallido, se prefiere el no-fallido más largo aunque sea más corto.
    cands2 = ["[CANDIDATO FALLIDO] boom que es un texto larguísimo de error", "ok corto"]
    assert _parse_winner("sin idea", 2, cands2) == 1


async def test_swarm_no_agent_fails():
    run, _agent = make_world()
    events: list[dict] = []

    async def publish(run_id, event):
        events.append(event)

    db = FakeDB([run, None])  # scalar del agente devuelve None

    @asynccontextmanager
    async def factory():
        yield db

    ScriptedSession.configure([], [])
    await execute_swarm_run(
        run.id, session_factory=factory, session_cls=ScriptedSession,
        tools=[EchoTool()], publish=publish,
    )
    assert run.status == "failed"
    assert events[-1]["status"] == "failed"
