"""Entrypoint del worker de AgentForge.

    python worker.py [--consumer NOMBRE]

Escalable horizontalmente: lanza N procesos con nombres de consumer distintos.
"""

import argparse
import asyncio
import logging
import os
import signal

from app.queue.worker import ensure_group, worker_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("agentforge.worker")


async def main(consumer_name: str) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await ensure_group()
    logger.info("Worker %s escuchando la cola de runs", consumer_name)
    await worker_loop(consumer_name, stop_event=stop_event)
    logger.info("Worker %s detenido limpiamente", consumer_name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--consumer", default=f"worker-{os.getpid()}")
    args = parser.parse_args()
    asyncio.run(main(args.consumer))
