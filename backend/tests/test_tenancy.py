"""Tests de multi-tenancy (orgs + membresías) sin Postgres.

Se prueba la lógica del service con un fake de AsyncSession (captura adds,
devuelve objetos en memoria para scalar/scalars) y la lógica de roles. El
router se prueba con TestClient sobrescribiendo get_current_user y get_db.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.routers import orgs as orgs_router
from app.security import get_current_user
from app.tenancy import service
from app.tenancy.models import Membership, Organization


def _apply_defaults(obj) -> None:
    """Simula los defaults que aplicaría la BD al hacer INSERT."""
    if isinstance(obj, Organization):
        if obj.id is None:
            obj.id = uuid.uuid4()
        if obj.plan is None:
            obj.plan = "free"
        if obj.max_runs_per_day is None:
            obj.max_runs_per_day = 100
        if obj.max_cost_usd_per_day is None:
            obj.max_cost_usd_per_day = 10.0
        if obj.created_at is None:
            obj.created_at = datetime.now(UTC)
    elif isinstance(obj, Membership):
        if obj.role is None:
            obj.role = "member"
        if obj.created_at is None:
            obj.created_at = datetime.now(UTC)


class FakeSession:
    """AsyncSession mínima en memoria.

    Captura .add() en `added`. scalar/scalars/get devuelven valores preconfigurados
    (next_membership / next_orgs / next_org), evitando interpretar SQL.
    """

    def __init__(self, *, membership=None, membership_seq=None, orgs=None, org=None):
        self.added: list = []
        self.deleted: list = []
        self.next_membership = membership
        # Cola opcional de resultados para scalar() en orden (útil cuando un
        # endpoint hace varias consultas de membresía distintas).
        self._scalar_queue = list(membership_seq) if membership_seq is not None else None
        self.next_orgs = orgs or []
        self.next_org = org

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
        if self._scalar_queue is not None:
            return self._scalar_queue.pop(0) if self._scalar_queue else None
        return self.next_membership

    async def scalars(self, _query):
        return list(self.next_orgs)

    async def get(self, _model, _pk):
        return self.next_org


# --------------------------- service: require_role ---------------------------


def test_require_role_owner_and_admin_pass():
    for role in ("owner", "admin"):
        m = Membership(org_id=uuid.uuid4(), user_id=uuid.uuid4(), role=role)
        service.require_role(m, "owner", "admin")  # no lanza


def test_require_role_member_fails():
    m = Membership(org_id=uuid.uuid4(), user_id=uuid.uuid4(), role="member")
    with pytest.raises(PermissionError):
        service.require_role(m, "owner", "admin")


def test_require_role_none_fails():
    with pytest.raises(PermissionError):
        service.require_role(None, "owner", "admin")


# ------------------------------ service: orgs --------------------------------


async def test_create_org_adds_org_and_owner_membership():
    db = FakeSession()
    owner_id = uuid.uuid4()

    org = await service.create_org(db, name="Acme", owner_user_id=owner_id)

    assert isinstance(org, Organization)
    assert org.name == "Acme"
    assert org.plan == "free"
    assert org.max_runs_per_day == 100
    assert org.max_cost_usd_per_day == 10.0

    orgs = [o for o in db.added if isinstance(o, Organization)]
    members = [m for m in db.added if isinstance(m, Membership)]
    assert len(orgs) == 1 and len(members) == 1
    assert members[0].role == "owner"
    assert members[0].user_id == owner_id
    assert members[0].org_id == org.id


async def test_list_orgs_for_user_returns_memory_objects():
    orgs = [Organization(name="A"), Organization(name="B")]
    db = FakeSession(orgs=orgs)
    result = await service.list_orgs_for_user(db, uuid.uuid4())
    assert [o.name for o in result] == ["A", "B"]


async def test_get_membership_returns_configured():
    m = Membership(org_id=uuid.uuid4(), user_id=uuid.uuid4(), role="admin")
    db = FakeSession(membership=m)
    assert await service.get_membership(db, m.org_id, m.user_id) is m


async def test_get_membership_none_when_absent():
    db = FakeSession(membership=None)
    assert await service.get_membership(db, uuid.uuid4(), uuid.uuid4()) is None


async def test_add_member_new():
    db = FakeSession(membership=None)
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    m = await service.add_member(db, org_id=org_id, user_id=user_id, role="admin")
    assert m.role == "admin"
    assert m in db.added


async def test_add_member_existing_updates_role():
    existing = Membership(org_id=uuid.uuid4(), user_id=uuid.uuid4(), role="member")
    db = FakeSession(membership=existing)
    m = await service.add_member(
        db, org_id=existing.org_id, user_id=existing.user_id, role="admin"
    )
    assert m is existing
    assert m.role == "admin"
    assert existing not in db.added  # no se re-inserta


async def test_remove_member_deletes_when_present():
    existing = Membership(org_id=uuid.uuid4(), user_id=uuid.uuid4(), role="member")
    db = FakeSession(membership=existing)
    await service.remove_member(db, org_id=existing.org_id, user_id=existing.user_id)
    assert existing in db.deleted


# ------------------------------ router (TestClient) --------------------------


def _make_client(db: FakeSession, user_id: uuid.UUID) -> TestClient:
    app = FastAPI()
    app.include_router(orgs_router.router)

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
    assert hasattr(orgs_router, "router")
    assert orgs_router.router.prefix == "/api/orgs"


def test_create_org_endpoint_makes_user_owner():
    db = FakeSession()
    user_id = uuid.uuid4()
    client = _make_client(db, user_id)

    resp = client.post("/api/orgs", json={"name": "Acme"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Acme"
    assert body["plan"] == "free"

    members = [m for m in db.added if isinstance(m, Membership)]
    assert len(members) == 1
    assert members[0].role == "owner"
    assert members[0].user_id == user_id


def test_member_cannot_add_members_403():
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    member = Membership(org_id=org_id, user_id=user_id, role="member")
    db = FakeSession(membership=member)
    client = _make_client(db, user_id)

    resp = client.post(
        f"/api/orgs/{org_id}/members",
        json={"user_id": str(uuid.uuid4()), "role": "member"},
    )
    assert resp.status_code == 403


def test_admin_can_add_members_201():
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    admin = Membership(org_id=org_id, user_id=user_id, role="admin")
    # 1a consulta: autorización (admin). 2a: existencia del nuevo miembro (None).
    db = FakeSession(membership_seq=[admin, None])
    client = _make_client(db, user_id)

    resp = client.post(
        f"/api/orgs/{org_id}/members",
        json={"user_id": str(uuid.uuid4()), "role": "member"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "member"


def test_get_org_404_when_not_member():
    db = FakeSession(membership=None)
    client = _make_client(db, uuid.uuid4())
    resp = client.get(f"/api/orgs/{uuid.uuid4()}")
    assert resp.status_code == 404
