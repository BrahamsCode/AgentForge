"""Dependencias FastAPI para el scoping por organización.

La organización activa se resuelve del header ``X-Org-Id``:
- ausente  → contexto personal (org_id = None); los agentes/runs del usuario
  sin organización siguen funcionando (compatibilidad hacia atrás).
- presente → se valida la membresía (403 si no pertenece) y se aplican los
  límites de la organización.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Run, User
from app.security import get_current_user
from app.tenancy.models import Organization
from app.tenancy.service import get_membership


async def get_active_org(
    x_org_id: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Organization | None:
    """Organización activa validada por membresía, o None (contexto personal)."""
    if not x_org_id:
        return None
    try:
        org_id = uuid.UUID(x_org_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Org-Id no es un UUID válido")

    membership = await get_membership(db, org_id, user.id)
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No perteneces a esa organización")
    org = await db.scalar(select(Organization).where(Organization.id == org_id))
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organización no encontrada")
    return org


async def enforce_daily_limits(db: AsyncSession, org: Organization) -> None:
    """Aplica max_runs_per_day y max_cost_usd_per_day de la organización.

    Lanza HTTP 429 si se superan. En contexto personal (org None) no aplica.
    """
    since = datetime.now(UTC) - timedelta(days=1)
    runs_today, cost_today = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Run.total_cost_usd), 0.0))
            .where(Run.org_id == org.id, Run.created_at >= since)
        )
    ).one()

    if runs_today >= org.max_runs_per_day:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Límite diario de runs alcanzado ({org.max_runs_per_day}) para la organización",
        )
    if cost_today >= org.max_cost_usd_per_day:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Límite diario de costo alcanzado (${org.max_cost_usd_per_day}) para la organización",
        )
