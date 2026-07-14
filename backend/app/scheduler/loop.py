"""Scheduler de runs programados (CU-3): cada minuto lanza hijos de las
plantillas cuyo cron coincide.

Una plantilla es un Run con status="scheduled" y schedule_cron; nunca se
ejecuta directamente. En cada disparo se crea un Run hijo (parent_run_id) que
sí se encola. La config de webhook viaja en checkpoint["notify"] y el motor la
usa al terminar el hijo.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.scheduler.cron import matches

logger = logging.getLogger(__name__)


async def spawn_due_runs(now: datetime, *, session_factory, enqueue) -> list[uuid.UUID]:
    """Lanza los hijos de las plantillas cuyo cron coincide con `now`.

    Devuelve los ids de los runs hijos creados. Idempotente por minuto:
    registra el último minuto disparado en checkpoint["last_fired_minute"].
    """
    from app.models import Run

    minute_key = now.strftime("%Y-%m-%dT%H:%M")
    spawned: list[uuid.UUID] = []

    async with session_factory() as db:
        templates = list(
            await db.scalars(select(Run).where(Run.status == "scheduled"))
        )
        for template in templates:
            if not template.schedule_cron:
                continue
            try:
                if not matches(template.schedule_cron, now):
                    continue
            except ValueError:
                logger.warning("Cron inválido en run %s: %r", template.id, template.schedule_cron)
                continue
            checkpoint = template.checkpoint or {}
            if checkpoint.get("last_fired_minute") == minute_key:
                continue  # ya disparado este minuto

            child = Run(
                agent_id=template.agent_id,
                team_id=template.team_id,
                goal=template.goal,
                status="queued",
                parent_run_id=template.id,
                created_by=template.created_by,
                checkpoint={"notify": checkpoint.get("notify")} if checkpoint.get("notify") else None,
            )
            db.add(child)
            template.checkpoint = {**checkpoint, "last_fired_minute": minute_key}
            await db.commit()
            await db.refresh(child)
            await enqueue(str(child.id))
            spawned.append(child.id)
            logger.info("Plantilla %s disparó run hijo %s", template.id, child.id)

    return spawned


async def scheduler_loop(*, stop_event: asyncio.Event | None = None, tick_seconds: float = 60.0,
                         session_factory=None, enqueue=None) -> None:
    if session_factory is None:
        from app.db import SessionLocal as session_factory  # noqa: N813
    if enqueue is None:
        from app.queue.bus import enqueue_run as enqueue

    while stop_event is None or not stop_event.is_set():
        try:
            await spawn_due_runs(datetime.now(UTC), session_factory=session_factory, enqueue=enqueue)
        except Exception:
            logger.exception("Error en el ciclo del scheduler")
        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), timeout=tick_seconds)
            else:
                await asyncio.sleep(tick_seconds)
        except TimeoutError:
            pass
