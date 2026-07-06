"""Tests del rate limiting de login (respaldado por Redis, con fakeredis)."""

import fakeredis.aioredis
import pytest

from app import ratelimit
from app.queue import redis_client


@pytest.fixture
def fake_redis(monkeypatch):
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_client, "_redis", r)
    return r


async def test_hit_allows_until_limit(fake_redis):
    key = "agentforge:login_attempts:demo"
    # limit=3 → los 3 primeros permitidos (False), el 4º supera (True)
    results = [await ratelimit.hit(key, limit=3, window_seconds=60) for _ in range(4)]
    assert results == [False, False, False, True]


async def test_reset_clears_counter(fake_redis):
    key = "agentforge:login_attempts:demo"
    for _ in range(3):
        await ratelimit.hit(key, limit=3, window_seconds=60)
    await ratelimit.reset(key)
    assert await ratelimit.hit(key, limit=3, window_seconds=60) is False


async def test_expire_is_set(fake_redis):
    key = "agentforge:login_attempts:demo"
    await ratelimit.hit(key, limit=5, window_seconds=120)
    assert 0 < await fake_redis.ttl(key) <= 120


async def test_fails_open_without_redis(monkeypatch):
    # Sin Redis disponible, no debe bloquear (disponibilidad > límite).
    def boom():
        raise RuntimeError("redis caído")

    monkeypatch.setattr(redis_client, "get_redis", boom)
    monkeypatch.setattr(redis_client, "_redis", None)
    assert await ratelimit.hit("k", limit=1, window_seconds=60) is False
