"""Notificaciones vía webhook para runs (CU-3: monitoreo continuo)."""

import logging

import httpx

logger = logging.getLogger(__name__)


async def notify(url: str, payload: dict) -> bool:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        logger.warning("Webhook a %s falló: %s", url, exc)
        return False
