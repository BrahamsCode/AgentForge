"""Tests del router de métricas (app.routers.metrics) sin Postgres.

Se monta un FastAPI de prueba con SOLO el router de métricas y se sobrescriben
get_db y get_current_user. El fake de AsyncSession devuelve filas agregadas
preconfiguradas para .execute(...).all() (en el orden en que metrics.py las pide:
por estado, por agente, por herramienta) y un entero para .scalar() (total de
pasos). También se valida el modelo Pydantic directamente.
"""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.routers import metrics as metrics_router
from app.routers.metrics import CostByAgent, MetricsSummary, ToolUsage
from app.security import get_current_user


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    """AsyncSession mínima: .execute() consume una cola de resultados en orden.

    metrics.py llama execute() 3 veces (estado, agente, herramienta) y luego
    scalar() 1 vez (total de pasos). No interpreta SQL: devuelve lo preconfigurado.
    """

    def __init__(self, *, status_rows, agent_rows, tool_rows, total_steps):
        self._execute_queue = [status_rows, agent_rows, tool_rows]
        self._total_steps = total_steps
        self.execute_calls = 0

    async def execute(self, _query):
        rows = self._execute_queue[self.execute_calls]
        self.execute_calls += 1
        return _FakeResult(rows)

    async def scalar(self, _query):
        return self._total_steps


def _make_client(db: FakeSession) -> TestClient:
    app = FastAPI()
    app.include_router(metrics_router.router)

    class FakeUser:
        id = uuid.uuid4()

    async def _override_get_db():
        yield db

    def _override_user():
        return FakeUser()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


def test_costs_endpoint_returns_summary_shape():
    agent_id = uuid.uuid4()
    db = FakeSession(
        status_rows=[
            ("completed", 3, 0.5, 1000),
            ("failed", 1, 0.1, 200),
        ],
        agent_rows=[
            (agent_id, "Agente A", 0.4, 800, 5),
            (None, None, 0.2, 400, 2),  # pasos sin agente (outerjoin → None)
        ],
        tool_rows=[
            ("web_search", 3),
            ("run_python", 2),
        ],
        total_steps=6,
    )
    client = _make_client(db)

    resp = client.get("/api/metrics/costs")
    assert resp.status_code == 200
    body = resp.json()

    assert body["runs_total"] == 4
    assert body["runs_completed"] == 3
    assert body["runs_failed"] == 1
    assert body["success_rate"] == 0.75  # 3/4
    assert body["total_cost_usd"] == 0.6
    assert body["total_tokens"] == 1200
    assert body["avg_steps_per_run"] == 1.5  # 6/4

    assert len(body["cost_by_agent"]) == 2
    assert body["cost_by_agent"][0]["agent_name"] == "Agente A"
    assert body["cost_by_agent"][1]["agent_name"] is None

    assert body["top_tools"][0] == {"tool": "web_search", "count": 3}


def test_costs_endpoint_empty_zero_runs():
    db = FakeSession(status_rows=[], agent_rows=[], tool_rows=[], total_steps=None)
    client = _make_client(db)

    resp = client.get("/api/metrics/costs")
    assert resp.status_code == 200
    body = resp.json()

    assert body["runs_total"] == 0
    assert body["success_rate"] == 0.0  # sin runs → 0.0, no ZeroDivision
    assert body["avg_steps_per_run"] == 0.0
    assert body["total_cost_usd"] == 0.0
    assert body["cost_by_agent"] == []
    assert body["top_tools"] == []


def test_since_days_query_validation():
    db = FakeSession(status_rows=[], agent_rows=[], tool_rows=[], total_steps=0)
    client = _make_client(db)
    # since_days fuera de rango (ge=1, le=365) → 422
    assert client.get("/api/metrics/costs?since_days=0").status_code == 422
    assert client.get("/api/metrics/costs?since_days=999").status_code == 422
    assert client.get("/api/metrics/costs?since_days=7").status_code == 200


def test_metrics_summary_pydantic_model():
    # Construcción directa del modelo con datos fake: valida el contrato Pydantic.
    summary = MetricsSummary(
        runs_total=2,
        runs_completed=1,
        runs_failed=1,
        success_rate=0.5,
        total_cost_usd=1.25,
        total_tokens=3000,
        avg_steps_per_run=4.0,
        cost_by_agent=[
            CostByAgent(agent_id=uuid.uuid4(), agent_name="X", cost_usd=1.0, tokens=2000, steps=8)
        ],
        top_tools=[ToolUsage(tool="web_fetch", count=5)],
    )
    dumped = summary.model_dump()
    assert dumped["success_rate"] == 0.5
    assert dumped["cost_by_agent"][0]["agent_name"] == "X"
    assert dumped["top_tools"][0]["count"] == 5


def test_cost_by_agent_allows_null_agent():
    # agent_id/agent_name opcionales (pasos sin atribución de agente).
    row = CostByAgent(agent_id=None, agent_name=None, cost_usd=0.0, tokens=0, steps=0)
    assert row.agent_id is None
    assert row.agent_name is None
