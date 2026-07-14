"""Tests de las herramientas de comunicación directa entre agentes."""

import uuid
from contextlib import asynccontextmanager

import pytest

from app.models import AgentMessage
from app.tools.base import ToolContext, ToolError
from app.tools.messaging import build_messaging_tools


class FakeDB:
    def __init__(self, existing=None):
        self.added: list = []
        self._existing = existing or []
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def scalars(self, _query):
        return iter(self._existing)


def _patch_session(monkeypatch, db):
    import app.db as db_module

    @asynccontextmanager
    async def factory():
        yield db

    monkeypatch.setattr(db_module, "SessionLocal", factory)


def _ctx(agent_name="Researcher-1", roster=None):
    return ToolContext(
        run_id=str(uuid.uuid4()),
        workspace_dir="/tmp/x",
        agent_id=str(uuid.uuid4()),
        agent_name=agent_name,
        roster=roster if roster is not None else {"Writer": str(uuid.uuid4())},
    )


def _tools():
    send, check = build_messaging_tools()
    assert send.name == "send_message"
    assert check.name == "check_messages"
    return send, check


async def test_send_to_valid_peer(monkeypatch):
    db = FakeDB()
    _patch_session(monkeypatch, db)
    send, _ = _tools()
    ctx = _ctx(roster={"Writer": str(uuid.uuid4())})

    out = await send.run({"to": "Writer", "content": "encontré la fuente clave"}, ctx)
    assert "Writer" in out
    assert len(db.added) == 1
    msg = db.added[0]
    assert isinstance(msg, AgentMessage)
    assert msg.to_agent == "Writer"
    assert msg.from_agent_name == "Researcher-1"
    assert db.committed


async def test_send_broadcast(monkeypatch):
    db = FakeDB()
    _patch_session(monkeypatch, db)
    send, _ = _tools()
    out = await send.run({"to": "all", "content": "aviso general"}, _ctx())
    assert "equipo" in out.lower()
    assert db.added[0].to_agent == "all"


async def test_send_unknown_recipient_errors(monkeypatch):
    db = FakeDB()
    _patch_session(monkeypatch, db)
    send, _ = _tools()
    with pytest.raises(ToolError, match="Destinatario desconocido"):
        await send.run({"to": "Fantasma", "content": "hola"}, _ctx(roster={"Writer": "x"}))


async def test_send_requires_fields(monkeypatch):
    send, _ = _tools()
    with pytest.raises(ToolError):
        await send.run({"to": "", "content": ""}, _ctx())


async def test_check_messages_reads_and_marks(monkeypatch):
    to_me = AgentMessage(
        run_id=uuid.uuid4(), from_agent_name="Writer", to_agent="Researcher-1",
        content="¿tienes la tabla?", read=False,
    )
    broadcast = AgentMessage(
        run_id=uuid.uuid4(), from_agent_name="Analyst", to_agent="all",
        content="ojo con las fechas", read=False,
    )
    db = FakeDB(existing=[to_me, broadcast])
    _patch_session(monkeypatch, db)
    _, check = _tools()

    out = await check.run({}, _ctx(agent_name="Researcher-1"))
    assert "Writer" in out and "¿tienes la tabla?" in out
    assert "Analyst" in out and "difusión" in out
    assert to_me.read is True and broadcast.read is True
    assert db.committed


async def test_check_messages_empty(monkeypatch):
    db = FakeDB(existing=[])
    _patch_session(monkeypatch, db)
    _, check = _tools()
    out = await check.run({}, _ctx())
    assert "No tienes mensajes" in out
