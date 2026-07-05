"""Tests del cron matcher y del scheduler de runs programados."""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.scheduler.cron import matches, parse_cron
from app.scheduler.loop import spawn_due_runs


def test_cron_wildcards_and_ranges():
    # Lunes 5 de enero de 2026, 09:30
    when = datetime(2026, 1, 5, 9, 30)
    assert matches("30 9 * * *", when)
    assert matches("*/15 9 * * *", when)  # 0,15,30,45
    assert matches("30 9 5 1 *", when)
    assert matches("30 9 * * 0", when)  # lunes = 0
    assert not matches("31 9 * * *", when)
    assert not matches("30 10 * * *", when)


def test_cron_lists_and_steps():
    when = datetime(2026, 7, 5, 8, 0)  # domingo
    assert matches("0 8,12,18 * * *", when)
    assert matches("0 0-12/4 * * *", when)  # 0,4,8,12
    assert matches("0 8 * * 6", when)  # domingo = 6


def test_cron_invalid_raises():
    with pytest.raises(ValueError):
        parse_cron("* * * *")  # solo 4 campos
    with pytest.raises(ValueError):
        parse_cron("99 * * * *")  # minuto fuera de rango


class FakeDB:
    def __init__(self, templates):
        self._templates = templates
        self.added = []
        self.commits = 0

    async def scalars(self, _query):
        return list(self._templates)

    def add(self, obj):
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        pass


def _template(cron, **extra):
    return SimpleNamespace(
        id=uuid.uuid4(), agent_id=uuid.uuid4(), team_id=None, goal="revisa fuentes",
        status="scheduled", schedule_cron=cron, checkpoint=extra.get("checkpoint"),
        created_by=uuid.uuid4(),
    )


async def _spawn(templates, when):
    from app.models import Run

    enqueued: list[str] = []

    async def enqueue(run_id):
        enqueued.append(run_id)

    db = FakeDB(templates)

    @asynccontextmanager
    async def factory():
        yield db

    spawned = await spawn_due_runs(when, session_factory=factory, enqueue=enqueue)
    children = [o for o in db.added if isinstance(o, Run)]
    return spawned, children, enqueued, db


async def test_spawn_matching_template():
    when = datetime(2026, 1, 5, 9, 0)
    tpl = _template("0 9 * * *", checkpoint={"notify": {"webhook_url": "https://hook"}})
    spawned, children, enqueued, db = await _spawn([tpl], when)

    assert len(spawned) == 1
    assert len(children) == 1
    child = children[0]
    assert child.status == "queued"
    assert child.parent_run_id == tpl.id
    assert child.checkpoint["notify"]["webhook_url"] == "https://hook"
    assert enqueued == [str(child.id)]
    # La plantilla registra el minuto para no re-disparar
    assert tpl.checkpoint["last_fired_minute"] == "2026-01-05T09:00"


async def test_no_spawn_when_cron_does_not_match():
    when = datetime(2026, 1, 5, 10, 0)
    tpl = _template("0 9 * * *")
    spawned, children, enqueued, _ = await _spawn([tpl], when)
    assert spawned == []
    assert children == []


async def test_idempotent_within_same_minute():
    when = datetime(2026, 1, 5, 9, 0)
    tpl = _template("0 9 * * *", checkpoint={"last_fired_minute": "2026-01-05T09:00"})
    spawned, children, _, _ = await _spawn([tpl], when)
    assert spawned == []


async def test_invalid_cron_skipped_not_raised():
    when = datetime(2026, 1, 5, 9, 0)
    tpl = _template("no-es-cron")
    spawned, children, _, _ = await _spawn([tpl], when)
    assert spawned == []
