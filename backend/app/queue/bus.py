"""Bus de mensajería sobre Redis Streams.

- Cola de jobs: stream RUNS_STREAM con consumer group RUNS_GROUP (workers).
- Eventos por run: stream `agentforge:events:{run_id}` — cada entrada tiene un
  único campo "data" con el evento serializado en JSON. El endpoint SSE lo lee
  desde el principio (histórico) y luego en vivo.
"""

import json

from app.queue.redis_client import get_redis

RUNS_STREAM = "agentforge:runs"
RUNS_GROUP = "workers"
EVENTS_KEY_TEMPLATE = "agentforge:events:{run_id}"

_EVENTS_TTL_SECONDS = 24 * 3600
_EVENTS_MAXLEN = 10_000


async def enqueue_run(run_id: str) -> None:
    await get_redis().xadd(RUNS_STREAM, {"run_id": run_id})


async def publish_event(run_id: str, event: dict) -> None:
    r = get_redis()
    key = EVENTS_KEY_TEMPLATE.format(run_id=run_id)
    await r.xadd(key, {"data": json.dumps(event, default=str)}, maxlen=_EVENTS_MAXLEN, approximate=True)
    await r.expire(key, _EVENTS_TTL_SECONDS)
