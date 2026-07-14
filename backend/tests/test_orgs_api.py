"""Tests del router de organizaciones (app.routers.orgs) vía TestClient.

FastAPI de prueba con SOLO el router de orgs y overrides de get_db /
get_current_user. El fake de AsyncSession opera en memoria (captura .add(),
aplica defaults de BD en flush/commit, y devuelve valores preconfigurados para
scalar/scalars/get). Cubre: crear org (201 + owner), listar, y que un member no
owner recibe 403 al añadir miembros (PermissionError → 403 en el router).
"""

import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.routers import orgs as orgs_router
from app.security import get_current_user
from app.tenancy.models import Membership, Organization


def _apply_defaults(obj) -> None:
    if isinstance(obj, Organization):
        obj.id = obj.id or uuid.uuid4()
        obj.plan = obj.plan or "free"
        obj.max_runs_per_day = obj.max_runs_per_day if obj.max_runs_per_day is not None else 100
        obj.max_cost_usd_per_day = (
            obj.max_cost_usd_per_day if obj.max_cost_usd_per_day is not None else 10.0
        )
        obj.created_at = obj.created_at or datetime.now(UTC)
    elif isinstance(obj, Membership):
        obj.role = obj.role or "member"
        obj.created_at = obj.created_at or datetime.now(UTC)


class FakeSession:
    """AsyncSession en memoria. `membership_seq` alimenta scalar() en orden."""

    def __init__(self, *, membership=None, membership_seq=None, orgs=None, org=None):
        self.added: list = []
        self.deleted: list = []
        self.next_membership = membership
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


def test_create_org_returns_201_and_owner():
    db = FakeSession()
    user_id = uuid.uuid4()
    client = _make_client(db, user_id)

    resp = client.post("/api/orgs", json={"name": "VivaTech"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "VivaTech"
    assert body["plan"] == "free"
    assert body["max_runs_per_day"] == 100

    members = [m for m in db.added if isinstance(m, Membership)]
    assert len(members) == 1
    assert members[0].role == "owner"
    assert members[0].user_id == user_id


def test_create_org_validation_empty_name_422():
    db = FakeSession()
    client = _make_client(db, uuid.uuid4())
    resp = client.post("/api/orgs", json={"name": ""})
    assert resp.status_code == 422


def test_list_orgs_returns_user_orgs():
    orgs = [Organization(name="Alpha"), Organization(name="Beta")]
    for o in orgs:
        _apply_defaults(o)
    db = FakeSession(orgs=orgs)
    client = _make_client(db, uuid.uuid4())

    resp = client.get("/api/orgs")
    assert resp.status_code == 200
    names = [o["name"] for o in resp.json()]
    assert names == ["Alpha", "Beta"]


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
    # 1a consulta scalar: autorización (admin). 2a: existencia del nuevo miembro (None).
    db = FakeSession(membership_seq=[admin, None])
    client = _make_client(db, user_id)

    resp = client.post(
        f"/api/orgs/{org_id}/members",
        json={"user_id": str(uuid.uuid4()), "role": "admin"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "admin"


def test_add_member_to_org_where_not_member_404():
    # Sin membresía del solicitante → _membership_or_404 lanza 404 antes del 403.
    db = FakeSession(membership=None)
    client = _make_client(db, uuid.uuid4())
    resp = client.post(
        f"/api/orgs/{uuid.uuid4()}/members",
        json={"user_id": str(uuid.uuid4()), "role": "member"},
    )
    assert resp.status_code == 404
