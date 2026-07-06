"""Router de multi-tenancy (backlog v2): organizaciones y membresías.

Alcance de este PR: base de tenancy — creación de organizaciones, gestión de
membresías con roles (owner|admin|member), límites de uso declarados por plan
(max_runs_per_day / max_cost_usd_per_day) y control de acceso a nivel de
organización.

SIGUIENTE PASO (fuera de alcance aquí, requiere tocar app/models.py):
añadir `org_id` a agents/runs para scoping por organización y aplicar los
límites declarados en el motor de ejecución / scheduler. Mientras tanto estas
tablas son puramente aditivas y no alteran el comportamiento existente.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User
from app.security import get_current_user
from app.tenancy import service
from app.tenancy.models import Organization

router = APIRouter(prefix="/api/orgs", tags=["orgs"])


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class OrgOut(BaseModel):
    id: uuid.UUID
    name: str
    plan: str
    max_runs_per_day: int
    max_cost_usd_per_day: float
    created_at: datetime

    model_config = {"from_attributes": True}


class MemberAdd(BaseModel):
    user_id: uuid.UUID
    role: str = Field(default="member", pattern="^(owner|admin|member)$")


class MemberOut(BaseModel):
    org_id: uuid.UUID
    user_id: uuid.UUID
    role: str

    model_config = {"from_attributes": True}


async def _membership_or_404(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID):
    membership = await service.get_membership(db, org_id, user_id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organización no encontrada")
    return membership


@router.post("", response_model=OrgOut, status_code=status.HTTP_201_CREATED)
async def create_org(
    body: OrgCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Organization:
    return await service.create_org(db, name=body.name, owner_user_id=user.id)


@router.get("", response_model=list[OrgOut])
async def list_orgs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Organization]:
    return await service.list_orgs_for_user(db, user.id)


@router.get("/{org_id}", response_model=OrgOut)
async def get_org(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Organization:
    # 404 si el usuario no es miembro (no se filtra la existencia de la org).
    await _membership_or_404(db, org_id, user.id)
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organización no encontrada")
    return org


@router.post(
    "/{org_id}/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    org_id: uuid.UUID,
    body: MemberAdd,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    membership = await _membership_or_404(db, org_id, user.id)
    try:
        service.require_role(membership, *service.MANAGE_ROLES)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    return await service.add_member(
        db, org_id=org_id, user_id=body.user_id, role=body.role
    )


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    membership = await _membership_or_404(db, org_id, user.id)
    try:
        service.require_role(membership, *service.MANAGE_ROLES)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    await service.remove_member(db, org_id=org_id, user_id=user_id)
