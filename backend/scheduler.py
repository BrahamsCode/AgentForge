"""Entrypoint del scheduler de runs programados (cron).

    python scheduler.py
"""

import asyncio
import logging
import signal

from app.scheduler.loop import scheduler_loop

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("agentforge.scheduler")


async def main() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    logger.info("Scheduler activo (tick de 60s)")
    await scheduler_loop(stop_event=stop_event)
    logger.info("Scheduler detenido")


if __name__ == "__main__":
    asyncio.run(main())
