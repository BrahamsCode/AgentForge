"""Tests del marketplace de plantillas de equipos, sin Postgres.

Se prueba el service con un fake de AsyncSession (captura .add(), asigna ids en
flush y devuelve resultados preconfigurados para scalar/scalars/execute) y el
router con TestClient sobrescribiendo get_current_user y get_db.
"""

import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.marketplace import service
from app.marketplace.builtin import BUILTIN_TEMPLATES
from app.marketplace.models import TeamTemplate
from app.models import Agent, Team, TeamMember
from app.routers import templates as templates_router
from app.security import get_current_user


def _apply_defaults(obj) -> None:
    """Simula los defaults/PK que aplicaría la BD al hacer INSERT."""
    if isinstance(obj, (Agent, Team, TeamTemplate)):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(UTC)


class _Result:
    """Envuelve una secuencia y expone .all() como db.execute(...).all()."""

    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class FakeSession:
    """AsyncSession mínima en memoria.

    scalar/scalars/execute consumen colas preconfiguradas (scalar_seq,
    scalars_seq, execute_seq) en orden; si se agotan devuelven None/[].
    """

    def __init__(self, *, scalar_seq=None, scalars_seq=None, execute_seq=None):
        self.added: list = []
        self.deleted: list = []
        self._scalar_seq = list(scalar_seq) if scalar_seq is not None else []
        self._scalars_seq = list(scalars_seq) if scalars_seq is not None else []
        self._execute_seq = list(execute_seq) if execute_seq is not None else []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            _apply_defaults(obj)

    async def commit(self):
        for obj in self.added:
            _apply_defaults(obj)

    async def refresh(self, obj):
        _apply_defaults(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def scalar(self, _query):
        return self._scalar_seq.pop(0) if self._scalar_seq else None

    async def scalars(self, _query):
        return self._scalars_seq.pop(0) if self._scalars_seq else []

    async def execute(self, _query):
        return self._execute_seq.pop(0) if self._execute_seq else _Result([])


def _sample_template() -> TeamTemplate:
    return TeamTemplate(
        id=uuid.uuid4(),
        name="Investigación de prueba",
        description="Plantilla de prueba",
        category="research",
        spec={
            "orchestrator": {
                "name": "Coordinador",
                "role": "orchestrator",
                "model_provider": "anthropic",
                "model_name": "claude-opus-4-8",
                "system_prompt": "Orquesta.",
                "max_steps": 40,
                "max_cost_usd": 3.0,
            },
            "members": [
                {
                    "name": "Investigador A",
                    "role": "researcher",
                    "model_provider": "anthropic",
                    "model_name": "claude-sonnet-5",
                    "system_prompt": "Investiga.",
                    "max_steps": 25,
                    "max_cost_usd": 1.5,
                    "specialty": "búsqueda web",
                },
                {
                    "name": "Redactor",
                    "role": "writer",
                    "model_provider": "anthropic",
                    "model_name": "claude-sonnet-5",
                    "system_prompt": "Redacta.",
                    "max_steps": 15,
                    "max_cost_usd": 1.0,
                    "specialty": "redacción",
                },
            ],
        },
        is_builtin=False,
        created_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )


# ------------------------------ service: instantiate -------------------------


async def test_instantiate_creates_agents_team_and_members():
    template = _sample_template()
    owner_id = uuid.uuid4()
    db = FakeSession()

    team = await service.instantiate(db, template=template, owner_user_id=owner_id)

    agents = [o for o in db.added if isinstance(o, Agent)]
    teams = [o for o in db.added if isinstance(o, Team)]
    members = [o for o in db.added if isinstance(o, TeamMember)]

    # 1 orquestador + 2 miembros
    assert len(agents) == 3
    assert len(teams) == 1
    assert len(members) == 2

    # created_by correcto en todos los agentes
    assert all(a.created_by == owner_id for a in agents)

    # el orquestador del spec está presente y es el del equipo
    orchestrator = next(a for a in agents if a.role == "orchestrator")
    assert orchestrator.name == "Coordinador"
    assert orchestrator.model_name == "claude-opus-4-8"
    assert team.orchestrator_agent_id == orchestrator.id

    # miembros con specialty del spec
    specialties = {m.specialty for m in members}
    assert specialties == {"búsqueda web", "redacción"}

    # todos los TeamMember apuntan al equipo creado
    assert all(m.team_id == team.id for m in members)
    member_agent_ids = {m.agent_id for m in members}
    non_orch_ids = {a.id for a in agents if a.role != "orchestrator"}
    assert member_agent_ids == non_orch_ids


# ------------------------------ service: seed_builtins -----------------------


async def test_seed_builtins_creates_when_absent():
    # scalars() (nombres existentes) devuelve [] -> se crean todas
    db = FakeSession(scalars_seq=[[]])
    await service.seed_builtins(db)

    created = [o for o in db.added if isinstance(o, TeamTemplate)]
    assert len(created) == len(BUILTIN_TEMPLATES)
    assert all(t.is_builtin is True for t in created)
    assert all(t.created_by is None for t in created)
    assert {t.name for t in created} == {t["name"] for t in BUILTIN_TEMPLATES}


async def test_seed_builtins_is_idempotent():
    existing_names = [t["name"] for t in BUILTIN_TEMPLATES]
    db = FakeSession(scalars_seq=[existing_names])
    await service.seed_builtins(db)
    assert [o for o in db.added if isinstance(o, TeamTemplate)] == []


# ------------------------------ builtin spec shape ---------------------------


def test_builtin_templates_have_expected_shape():
    assert len(BUILTIN_TEMPLATES) >= 3
    names = {t["name"] for t in BUILTIN_TEMPLATES}
    assert {"Investigación profunda", "Análisis de datos", "Monitoreo"} <= names

    for tpl in BUILTIN_TEMPLATES:
        assert tpl["name"] and tpl["description"]
        spec = tpl["spec"]
        orch = spec["orchestrator"]
        for field in ("name", "role", "model_provider", "model_name", "system_prompt"):
            assert orch[field]
        assert orch["model_name"] == "claude-opus-4-8"
        assert spec["members"], "members no debe estar vacío"
        for member in spec["members"]:
            assert member["name"] and member["role"]
            assert member["model_name"] == "claude-sonnet-5"
            assert "specialty" in member


# --------------------------- service: save_team_as_template ------------------


async def test_save_team_as_template_builds_spec():
    owner_id = uuid.uuid4()
    orch = Agent(
        id=uuid.uuid4(),
        name="Coordinador",
        role="orchestrator",
        model_provider="anthropic",
        model_name="claude-opus-4-8",
        system_prompt="Orquesta.",
        max_steps=40,
        max_cost_usd=3.0,
        created_by=owner_id,
    )
    team = Team(
        id=uuid.uuid4(),
        name="Equipo origen",
        description="desc",
        orchestrator_agent_id=orch.id,
    )
    member = Agent(
        id=uuid.uuid4(),
        name="Analista",
        role="analyst",
        model_provider="anthropic",
        model_name="claude-sonnet-5",
        system_prompt="Analiza.",
        max_steps=20,
        max_cost_usd=1.5,
        created_by=owner_id,
    )
    # scalar: primero el team, luego el orquestador. execute: filas (agent, specialty).
    db = FakeSession(
        scalar_seq=[team, orch],
        execute_seq=[_Result([(member, "síntesis")])],
    )

    tpl = await service.save_team_as_template(
        db,
        team_id=team.id,
        name="Mi plantilla",
        description="guardada",
        category="research",
        owner_user_id=owner_id,
    )

    assert isinstance(tpl, TeamTemplate)
    assert tpl.is_builtin is False
    assert tpl.created_by == owner_id
    assert tpl.spec["orchestrator"]["name"] == "Coordinador"
    assert tpl.spec["orchestrator"]["model_name"] == "claude-opus-4-8"
    assert len(tpl.spec["members"]) == 1
    assert tpl.spec["members"][0]["name"] == "Analista"
    assert tpl.spec["members"][0]["specialty"] == "síntesis"
    assert tpl in db.added


async def test_save_team_as_template_missing_team_raises():
    db = FakeSession(scalar_seq=[None])
    try:
        await service.save_team_as_template(
            db,
            team_id=uuid.uuid4(),
            name="x",
            description="",
            category="general",
            owner_user_id=uuid.uuid4(),
        )
        assert False, "debía lanzar ValueError"
    except ValueError:
        pass


# ------------------------------ router (TestClient) --------------------------


def _make_client(db: FakeSession, user_id: uuid.UUID) -> TestClient:
    app = FastAPI()
    app.include_router(templates_router.router)

    class FakeUser:
        def __init__(self, uid):
            self.id = uid

    async def _override_get_db():
        yield db

    def _override_user():
        return FakeUser(user_id)

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


def test_router_is_named_router():
    assert hasattr(templates_router, "router")
    assert templates_router.router.prefix == "/api/templates"


def test_list_templates_endpoint_seeds_and_returns():
    user_id = uuid.uuid4()
    tpl = _sample_template()
    # 1a scalars: nombres builtin existentes (todos, no re-siembra). 2a: lista visible.
    db = FakeSession(
        scalars_seq=[[t["name"] for t in BUILTIN_TEMPLATES], [tpl]]
    )
    client = _make_client(db, user_id)

    resp = client.get("/api/templates")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == tpl.name
    assert body[0]["category"] == "research"


def test_delete_builtin_forbidden():
    user_id = uuid.uuid4()
    builtin = TeamTemplate(
        id=uuid.uuid4(),
        name="Investigación profunda",
        description="",
        category="research",
        spec={"orchestrator": {}, "members": []},
        is_builtin=True,
        created_by=None,
    )
    db = FakeSession(scalar_seq=[builtin])
    client = _make_client(db, user_id)

    resp = client.delete(f"/api/templates/{builtin.id}")
    assert resp.status_code == 403


def test_delete_other_users_template_forbidden():
    user_id = uuid.uuid4()
    other = TeamTemplate(
        id=uuid.uuid4(),
        name="Ajena",
        description="",
        category="general",
        spec={"orchestrator": {}, "members": []},
        is_builtin=False,
        created_by=uuid.uuid4(),  # otro usuario
    )
    db = FakeSession(scalar_seq=[other])
    client = _make_client(db, user_id)

    resp = client.delete(f"/api/templates/{other.id}")
    assert resp.status_code == 403


def test_get_template_404():
    db = FakeSession(scalar_seq=[None])
    client = _make_client(db, uuid.uuid4())
    resp = client.get(f"/api/templates/{uuid.uuid4()}")
    assert resp.status_code == 404
