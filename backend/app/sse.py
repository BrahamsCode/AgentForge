"""Helpers de Server-Sent Events para el streaming de eventos de un run.

Los eventos viven en el stream Redis `agentforge:events:{run_id}` (campo
"data" = JSON). El generador emite primero el histórico y luego sigue en vivo
hasta el evento terminal (run_finished | run_cancelled).
"""

import asyncio
import json
import uuid

import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import User
from app.security import ALGORITHM

_bearer = HTTPBearer(auto_error=False)

_TERMINAL_EVENT_TYPES = {"run_finished", "run_cancelled"}
_BLOCK_MS = 15_000


async def get_user_from_header_or_query(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Como get_current_user, pero acepta también ?token= (EventSource no manda headers)."""
    raw = credentials.credentials if credentials else token
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales inválidas o ausentes")
    if not raw:
        raise unauthorized
    try:
        payload = jwt.decode(raw, get_settings().jwt_secret, algorithms=[ALGORITHM])
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise unauthorized
    return user


def format_sse(data: str, event_id: str | None = None) -> str:
    prefix = f"id: {event_id}\n" if event_id else ""
    return f"{prefix}data: {data}\n\n"


def _is_terminal(raw_json: str) -> bool:
    try:
        return json.loads(raw_json).get("type") in _TERMINAL_EVENT_TYPES
    except json.JSONDecodeError:
        return False


async def run_event_stream(run_id: str, *, run_is_terminal: bool = False, redis=None):
    """Generador async de frames SSE para un run.

    - Emite el histórico completo del stream Redis.
    - Si el run ya estaba terminal al conectar, corta tras el histórico.
    - Si no, bloquea con XREAD y emite eventos nuevos + keepalives, hasta ver
      un evento terminal.
    """
    if redis is None:
        from app.queue.redis_client import get_redis

        redis = get_redis()

    from app.queue.bus import EVENTS_KEY_TEMPLATE

    key = EVENTS_KEY_TEMPLATE.format(run_id=run_id)
    last_id = "0-0"
    try:
        # 1) Histórico
        for entry_id, fields in await redis.xrange(key):
            data = fields.get("data", "{}")
            yield format_sse(data, entry_id)
            last_id = entry_id
            if _is_terminal(data):
                return
        if run_is_terminal:
            return

        # 2) En vivo
        while True:
            batches = await redis.xread({key: last_id}, count=100, block=_BLOCK_MS)
            if not batches:
                yield ": ping\n\n"
                continue
            for _stream, entries in batches:
                for entry_id, fields in entries:
                    data = fields.get("data", "{}")
                    yield format_sse(data, entry_id)
                    last_id = entry_id
                    if _is_terminal(data):
                        return
    except asyncio.CancelledError:
        return
