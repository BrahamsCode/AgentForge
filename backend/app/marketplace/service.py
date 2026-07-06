"""Lógica de dominio del marketplace de plantillas de equipos.

Todo async sobre AsyncSession. Una plantilla (`TeamTemplate`) guarda en `spec`
la definición de un equipo preconfigurado (orquestador + miembros); al
instanciarla se crean Agent/Team/TeamMember reales de un clic.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketplace.builtin import BUILTIN_TEMPLATES
from app.marketplace.models import TeamTemplate
from app.models import Agent, Team, TeamMember

# Campos del spec que corresponden a atributos de Agent.
_AGENT_FIELDS = (
    "name",
    "role",
    "model_provider",
    "model_name",
    "system_prompt",
    "max_steps",
    "max_cost_usd",
)


async def list_templates(db: AsyncSession, user_id: uuid.UUID) -> list[TeamTemplate]:
    """Plantillas visibles para el usuario: builtin + las creadas por él."""
    result = await db.scalars(
        select(TeamTemplate)
        .where(
            (TeamTemplate.is_builtin.is_(True)) | (TeamTemplate.created_by == user_id)
        )
        .order_by(TeamTemplate.created_at.desc())
    )
    return list(result)


async def seed_builtins(db: AsyncSession) -> None:
    """Crea las plantillas builtin que aún no existen (idempotente por nombre)."""
    existing = set(
        await db.scalars(
            select(TeamTemplate.name).where(TeamTemplate.is_builtin.is_(True))
        )
    )
    created = False
    for tpl in BUILTIN_TEMPLATES:
        if tpl["name"] in existing:
            continue
        db.add(
            TeamTemplate(
                name=tpl["name"],
                description=tpl.get("description", ""),
                category=tpl.get("category", "general"),
                spec=tpl["spec"],
                is_builtin=True,
                created_by=None,
            )
        )
        created = True
    if created:
        await db.commit()


def _agent_from_spec(node: dict[str, Any], owner_user_id: uuid.UUID) -> Agent:
    """Construye un Agent a partir de un nodo del spec (orquestador o miembro)."""
    kwargs: dict[str, Any] = {
        field: node[field] for field in _AGENT_FIELDS if field in node
    }
    kwargs["created_by"] = owner_user_id
    return Agent(**kwargs)


async def instantiate(
    db: AsyncSession, *, template: TeamTemplate, owner_user_id: uuid.UUID
) -> Team:
    """Materializa una plantilla: crea el orquestador, los miembros y el equipo.

    Devuelve el Team creado (con orchestrator_agent_id y sus TeamMember).
    """
    spec = template.spec or {}
    orch_spec = spec.get("orchestrator") or {}
    members_spec = spec.get("members") or []

    orchestrator = _agent_from_spec(orch_spec, owner_user_id)
    db.add(orchestrator)

    member_agents: list[tuple[Agent, str]] = []
    for member_spec in members_spec:
        agent = _agent_from_spec(member_spec, owner_user_id)
        db.add(agent)
        member_agents.append((agent, member_spec.get("specialty", "")))

    await db.flush()  # asegura los .id de los agentes

    team = Team(
        name=template.name,
        description=template.description,
        orchestrator_agent_id=orchestrator.id,
    )
    db.add(team)
    await db.flush()  # asegura team.id

    for agent, specialty in member_agents:
        db.add(TeamMember(team_id=team.id, agent_id=agent.id, specialty=specialty))

    await db.commit()
    await db.refresh(team)
    return team


async def save_team_as_template(
    db: AsyncSession,
    *,
    team_id: uuid.UUID,
    name: str,
    description: str,
    category: str,
    owner_user_id: uuid.UUID,
) -> TeamTemplate:
    """Construye una plantilla a partir de un equipo existente y sus miembros."""
    team = await db.scalar(select(Team).where(Team.id == team_id))
    if team is None:
        raise ValueError("Equipo no encontrado")

    orch_spec: dict[str, Any] = {}
    if team.orchestrator_agent_id is not None:
        orchestrator = await db.scalar(
            select(Agent).where(Agent.id == team.orchestrator_agent_id)
        )
        if orchestrator is not None:
            orch_spec = _agent_to_spec(orchestrator)

    rows = (
        await db.execute(
            select(Agent, TeamMember.specialty)
            .join(TeamMember, TeamMember.agent_id == Agent.id)
            .where(TeamMember.team_id == team_id)
        )
    ).all()
    members_spec: list[dict[str, Any]] = []
    for agent, specialty in rows:
        node = _agent_to_spec(agent)
        node["specialty"] = specialty or ""
        members_spec.append(node)

    spec = {"orchestrator": orch_spec, "members": members_spec}
    template = TeamTemplate(
        name=name,
        description=description,
        category=category or "general",
        spec=spec,
        is_builtin=False,
        created_by=owner_user_id,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


def _agent_to_spec(agent: Agent) -> dict[str, Any]:
    """Extrae del Agent los campos que componen un nodo del spec."""
    return {field: getattr(agent, field) for field in _AGENT_FIELDS}
