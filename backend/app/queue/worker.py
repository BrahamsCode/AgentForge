"""Loop del worker: consume runs de Redis Streams y ejecuta el motor agéntico.

Resiliencia (O4): los mensajes van con consumer group + XACK tras procesar, y
XAUTOCLAIM recupera mensajes de consumers muertos, así un run encolado no se
pierde si el worker que lo tomó murió antes de terminar.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from redis.exceptions import ResponseError

from app.queue.bus import RUNS_GROUP, RUNS_STREAM
from app.queue.redis_client import get_redis

logger = logging.getLogger(__name__)

_CLAIM_MIN_IDLE_MS = 60_000
_BLOCK_MS = 5_000


async def ensure_group() -> None:
    try:
        await get_redis().xgroup_create(RUNS_STREAM, RUNS_GROUP, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def mark_run_failed(run_id: uuid.UUID, error: str) -> None:
    """Marca un run como failed si no está ya en estado terminal."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Run

    async with SessionLocal() as db:
        run = await db.scalar(select(Run).where(Run.id == run_id))
        if run is not None and run.status in ("queued", "running", "awaiting_approval"):
            run.status = "failed"
            run.error = error[:2000]
            run.finished_at = datetime.now(UTC)
            await db.commit()


async def _claim_stale(consumer_name: str) -> list:
    """Recupera mensajes pendientes de consumers muertos (best effort)."""
    try:
        result = await get_redis().xautoclaim(
            RUNS_STREAM, RUNS_GROUP, consumer_name, min_idle_time=_CLAIM_MIN_IDLE_MS, start_id="0-0"
        )
        # redis-py devuelve (next_start, messages[, deleted]) según versión
        messages = result[1] if isinstance(result, (list, tuple)) and len(result) >= 2 else []
        return list(messages or [])
    except (ResponseError, NotImplementedError):
        return []  # fakeredis o Redis antiguo sin XAUTOCLAIM


async def _process(message_id: str, fields: dict, mark_failed) -> None:
    r = get_redis()
    raw_run_id = fields.get("run_id", "")
    try:
        run_id = uuid.UUID(raw_run_id)
    except ValueError:
        logger.error("Mensaje %s con run_id inválido: %r", message_id, raw_run_id)
        await r.xack(RUNS_STREAM, RUNS_GROUP, message_id)
        return

    try:
        from app.engine.loop import execute_run

        logger.info("Ejecutando run %s (msg %s)", run_id, message_id)
        await execute_run(run_id)
    except Exception as exc:
        logger.exception("Run %s falló en el worker", run_id)
        try:
            await mark_failed(run_id, str(exc))
        except Exception:
            logger.exception("No se pudo marcar failed el run %s", run_id)
    finally:
        await r.xack(RUNS_STREAM, RUNS_GROUP, message_id)


async def worker_loop(
    consumer_name: str,
    *,
    stop_event: asyncio.Event | None = None,
    mark_failed=mark_run_failed,
    max_iterations: int | None = None,
) -> None:
    r = get_redis()
    iterations = 0
    while stop_event is None or not stop_event.is_set():
        if max_iterations is not None:
            if iterations >= max_iterations:
                return
            iterations += 1

        for message_id, fields in await _claim_stale(consumer_name):
            await _process(message_id, fields, mark_failed)

        try:
            batches = await r.xreadgroup(
                RUNS_GROUP, consumer_name, {RUNS_STREAM: ">"}, count=1, block=_BLOCK_MS
            )
        except ResponseError as exc:
            if "NOGROUP" in str(exc):
                await ensure_group()
                continue
            raise

        for _stream, messages in batches or []:
            for message_id, fields in messages:
                await _process(message_id, fields, mark_failed)
