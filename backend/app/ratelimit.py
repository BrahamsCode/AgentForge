"""Rate limiting simple respaldado por Redis (ventana deslizante por contador).

Se usa para acotar los intentos de login. Falla abierto: si Redis no está
disponible no bloquea el flujo (la disponibilidad prima sobre el límite).
"""

import logging

logger = logging.getLogger(__name__)


async def hit(key: str, *, limit: int, window_seconds: int) -> bool:
    """Registra un intento en `key`. Devuelve True si se superó el límite.

    Cuenta con INCR + EXPIRE en la primera pulsación de la ventana.
    """
    try:
        from app.queue.redis_client import get_redis

        r = get_redis()
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, window_seconds)
        return count > limit
    except Exception:  # Redis caído → no bloquear
        logger.warning("Rate limit no disponible (Redis); se permite el intento")
        return False


async def reset(key: str) -> None:
    try:
        from app.queue.redis_client import get_redis

        await get_redis().delete(key)
    except Exception:
        pass
