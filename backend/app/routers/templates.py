"""Router del marketplace de plantillas de equipos (backlog v2).

Permite listar plantillas (builtin + del usuario), ver su detalle, instanciarlas
para crear agentes+equipo reales de un clic, guardar un equipo existente como
plantilla y borrar las plantillas propias no-builtin.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.marketplace import service
from app.marketplace.models import TeamTemplate
from app.models import TeamMember, User
from app.security import get_current_user

router = APIRouter(prefix="/api/templates", tags=["templates"])


class TemplateOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str
    category: str
    spec: dict[str, Any]
    is_builtin: bool
    created_by: uuid.UUID | None
    created_at: datetime


class InstantiateOut(BaseModel):
    team_id: uuid.UUID
    agent_ids: list[uuid.UUID]


class FromTeamIn(BaseModel):
    team_id: uuid.UUID
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    category: str = "general"


async def _get_template_or_404(db: AsyncSession, template_id: uuid.UUID) -> TeamTemplate:
    template = await db.scalar(
        select(TeamTemplate).where(TeamTemplate.id == template_id)
    )
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plantilla no encontrada")
    return template


@router.get("", response_model=list[TemplateOut])
async def list_templates(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TeamTemplate]:
    stmt = select(TeamTemplate).order_by(TeamTemplate.created_at.desc())
    result = await db.scalars(stmt)
    return list(result.all())


@router.get("/{template_id}", response_model=TemplateOut)
async def get_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TeamTemplate:
	return await _get_template_or_404(db, template_id)


@router.post(
    "/{template_id}/instantiate",
    response_model=InstantiateOut,
    status_code=status.HTTP_201_CREATED,
)
async def instantiate_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InstantiateOut:
    template = await _get_template_or_404(db, template_id)
    team = await service.instantiate(db, template=template, owner_user_id=user.id)
    agent_ids: list[uuid.UUID] = []
    if team.orchestrator_agent_id is not None:
        agent_ids.append(team.orchestrator_agent_id)
    members = await db.scalars(
        select(TeamMember.agent_id).where(TeamMember.team_id == team.id)
    )
    agent_ids.extend(members)
    return InstantiateOut(team_id=team.id, agent_ids=agent_ids)


@router.post(
    "/from-team", response_model=TemplateOut, status_code=status.HTTP_201_CREATED
)
async def save_from_team(
    body: FromTeamIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TeamTemplate:
    try:
        return await service.save_team_as_template(
            db,
            team_id=body.team_id,
            name=body.name,
            description=body.description,
            category=body.category,
            owner_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    template = await _get_template_or_404(db, template_id)
    if template.is_builtin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "No se pueden borrar plantillas builtin"
        )
    if template.created_by != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Solo puedes borrar tus propias plantillas"
        )
    await db.delete(template)
    await db.commit()
