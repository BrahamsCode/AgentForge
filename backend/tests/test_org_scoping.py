"""Scoping por organización: resolución de org activa y límites diarios."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.tenancy.deps import enforce_daily_limits, get_active_org


class FakeScalarDB:
    def __init__(self, membership=None, org=None, count_cost=(0, 0.0)):
        self._membership = membership
        self._org = org
        self._count_cost = count_cost

    async def scalar(self, query):
        text = str(query).lower()
        if "memberships" in text:
            return self._membership
        if "organizations" in text:
            return self._org
        return None

    async def execute(self, _query):
        cc = self._count_cost

        class R:
            def one(self_inner):
                return cc

        return R()


async def test_no_header_is_personal_context():
    org = await get_active_org(x_org_id=None, db=FakeScalarDB(), user=SimpleNamespace(id=uuid.uuid4()))
    assert org is None


async def test_invalid_uuid_header_400():
    with pytest.raises(HTTPException) as exc:
        await get_active_org(x_org_id="no-uuid", db=FakeScalarDB(), user=SimpleNamespace(id=uuid.uuid4()))
    assert exc.value.status_code == 400


async def test_non_member_forbidden():
    user = SimpleNamespace(id=uuid.uuid4())
    db = FakeScalarDB(membership=None)  # no pertenece
    with pytest.raises(HTTPException) as exc:
        await get_active_org(x_org_id=str(uuid.uuid4()), db=db, user=user)
    assert exc.value.status_code == 403


async def test_member_resolves_org():
    org_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4())
    org = SimpleNamespace(id=org_id, name="ACME")
    db = FakeScalarDB(membership=SimpleNamespace(role="member"), org=org)
    resolved = await get_active_org(x_org_id=str(org_id), db=db, user=user)
    assert resolved is org


async def test_daily_run_limit_exceeded_429():
    org = SimpleNamespace(id=uuid.uuid4(), max_runs_per_day=5, max_cost_usd_per_day=10.0)
    db = FakeScalarDB(count_cost=(5, 0.0))  # ya 5 runs hoy
    with pytest.raises(HTTPException) as exc:
        await enforce_daily_limits(db, org)
    assert exc.value.status_code == 429
    assert "runs" in exc.value.detail


async def test_daily_cost_limit_exceeded_429():
    org = SimpleNamespace(id=uuid.uuid4(), max_runs_per_day=100, max_cost_usd_per_day=1.0)
    db = FakeScalarDB(count_cost=(3, 1.5))  # costo por encima del límite
    with pytest.raises(HTTPException) as exc:
        await enforce_daily_limits(db, org)
    assert exc.value.status_code == 429
    assert "costo" in exc.value.detail


async def test_within_limits_ok():
    org = SimpleNamespace(id=uuid.uuid4(), max_runs_per_day=100, max_cost_usd_per_day=10.0)
    db = FakeScalarDB(count_cost=(2, 0.3))
    await enforce_daily_limits(db, org)  # no lanza
