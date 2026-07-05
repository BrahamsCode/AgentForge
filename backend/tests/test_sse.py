"""Tests del generador SSE y de la auth por query token, con fakeredis."""

import json
import uuid

import fakeredis.aioredis
import jwt
import pytest

from app.config import get_settings
from app.queue.bus import EVENTS_KEY_TEMPLATE
from app.security import ALGORITHM, create_access_token
from app.sse import format_sse, run_event_stream


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


async def _preload(r, run_id: str, events: list[dict]):
    key = EVENTS_KEY_TEMPLATE.format(run_id=run_id)
    for e in events:
        await r.xadd(key, {"data": json.dumps(e)})


async def test_stream_emits_history_and_stops_at_terminal(fake_redis):
    run_id = "run-1"
    await _preload(fake_redis, run_id, [
        {"type": "step", "step": 1},
        {"type": "step", "step": 2},
        {"type": "run_finished", "status": "completed"},
        {"type": "step", "step": 99},  # después del terminal: no debe emitirse
    ])

    frames = [f async for f in run_event_stream(run_id, redis=fake_redis)]
    datas = [json.loads(f.split("data: ", 1)[1].strip()) for f in frames if "data: " in f]
    assert [d.get("step", d["type"]) for d in datas] == [1, 2, "run_finished"]


async def test_stream_terminal_run_exhausts_history_only(fake_redis):
    run_id = "run-2"
    await _preload(fake_redis, run_id, [{"type": "step", "step": 1}])
    frames = [f async for f in run_event_stream(run_id, run_is_terminal=True, redis=fake_redis)]
    assert len([f for f in frames if "data: " in f]) == 1


def test_format_sse():
    assert format_sse('{"a":1}', "5-0") == 'id: 5-0\ndata: {"a":1}\n\n'
    assert format_sse("x") == "data: x\n\n"


def test_query_token_roundtrip():
    """El token que genera security.py se decodifica con el mismo secreto (base de la auth SSE)."""
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
    assert uuid.UUID(payload["sub"]) == user_id

    with pytest.raises(jwt.PyJWTError):
        jwt.decode(token + "x", get_settings().jwt_secret, algorithms=[ALGORITHM])
