import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Agent, Team, TeamMember, User
from app.security import get_current_user

router = APIRouter(prefix="/api/teams", tags=["teams"])


class MemberIn(BaseModel):
    agent_id: uuid.UUID
    specialty: str = ""


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    orchestrator_agent_id: uuid.UUID
    members: list[MemberIn] = Field(min_length=1, max_length=20)


class MemberOut(BaseModel):
    agent_id: uuid.UUID
    agent_name: str
    specialty: str


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    orchestrator_agent_id: uuid.UUID | None
    created_at: datetime
    members: list[MemberOut] = []


async def _validate_agents(db: AsyncSession, ids: list[uuid.UUID]) -> None:
    found = set(
        (await db.scalars(select(Agent.id).where(Agent.id.in_(ids)))).all()
    )
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Agentes inexistentes: {missing}")


async def _members_out(db: AsyncSession, team_id: uuid.UUID) -> list[MemberOut]:
    rows = (
        await db.execute(
            select(TeamMember.agent_id, Agent.name, TeamMember.specialty)
            .join(Agent, Agent.id == TeamMember.agent_id)
            .where(TeamMember.team_id == team_id)
        )
    ).all()
    return [MemberOut(agent_id=a, agent_name=n, specialty=s) for a, n, s in rows]


@router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(
    body: TeamCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TeamOut:
    await _validate_agents(
        db, [body.orchestrator_agent_id] + [m.agent_id for m in body.members]
    )
    team = Team(
        name=body.name,
        description=body.description,
        orchestrator_agent_id=body.orchestrator_agent_id,
    )
    db.add(team)
    await db.flush()
    for member in body.members:
        db.add(TeamMember(team_id=team.id, agent_id=member.agent_id, specialty=member.specialty))
    await db.commit()
    await db.refresh(team)
    out = TeamOut.model_validate(team)
    out.members = await _members_out(db, team.id)
    return out


@router.get("", response_model=list[TeamOut])
async def list_teams(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[TeamOut]:
    teams = list(await db.scalars(select(Team).order_by(Team.created_at.desc())))
    result = []
    for team in teams:
        out = TeamOut.model_validate(team)
        out.members = await _members_out(db, team.id)
        result.append(out)
    return result


@router.get("/{team_id}", response_model=TeamOut)
async def get_team(
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TeamOut:
    team = await db.scalar(select(Team).where(Team.id == team_id))
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Equipo no encontrado")
    out = TeamOut.model_validate(team)
    out.members = await _members_out(db, team.id)
    return out


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> None:
    team = await db.scalar(select(Team).where(Team.id == team_id))
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Equipo no encontrado")
    await db.execute(delete(TeamMember).where(TeamMember.team_id == team_id))
    await db.delete(team)
    await db.commit()
