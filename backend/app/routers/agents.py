import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.llm.client import get_llm_client
from app.models import Agent, User
from app.schemas import AgentCreate, AgentOut, AgentUpdate, AskRequest, AskResponse
from app.security import get_current_user
from app.tenancy.deps import get_active_org
from app.tenancy.models import Organization

router = APIRouter(prefix="/api/agents", tags=["agents"])


async def _get_agent_or_404(
    agent_id: uuid.UUID, db: AsyncSession, org: Organization | None
) -> Agent:
    # Scoping por organización: un agente solo es accesible desde el contexto
    # (personal o de org) en el que fue creado. Si no coincide devolvemos 404
    # (no 403) para no filtrar la existencia de recursos de otras orgs.
    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id, Agent.org_id == (org.id if org else None)
        )
    )
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agente no encontrado")
    return agent


@router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    org: Organization | None = Depends(get_active_org),
) -> Agent:
    agent = Agent(**body.model_dump(), created_by=user.id, org_id=org.id if org else None)
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.get("", response_model=list[AgentOut])
async def list_agents(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
    org: Organization | None = Depends(get_active_org),
) -> list[Agent]:
    # Con org activa → agentes de la org; sin org → agentes personales (org_id NULL)
    query = select(Agent).where(Agent.org_id == (org.id if org else None))
    result = await db.scalars(query.order_by(Agent.created_at.desc()))
    return list(result)


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
    org: Organization | None = Depends(get_active_org),
) -> Agent:
    return await _get_agent_or_404(agent_id, db, org)


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
    org: Organization | None = Depends(get_active_org),
) -> Agent:
    agent = await _get_agent_or_404(agent_id, db, org)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
    org: Organization | None = Depends(get_active_org),
) -> None:
    agent = await _get_agent_or_404(agent_id, db, org)
    await db.delete(agent)
    await db.commit()


@router.post("/{agent_id}/ask", response_model=AskResponse)
async def ask_agent(
    agent_id: uuid.UUID,
    body: AskRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
    org: Organization | None = Depends(get_active_org),
) -> AskResponse:
    """Entregable de la Fase 0: pregunta simple a un agente, sin herramientas.

    En la Fase 1 esto se reemplaza por runs encolados en Redis Streams con
    loop agéntico y trace completo.
    """
    agent = await _get_agent_or_404(agent_id, db, org)
    try:
        result = await get_llm_client().complete(
            provider=agent.model_provider,
            model=agent.model_name,
            system_prompt=agent.system_prompt,
            user_message=body.question,
            temperature=agent.temperature,
        )
    except RuntimeError as exc:  # API key del proveedor no configurada
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))

    return AskResponse(
        answer=result.text,
        model_provider=result.model_provider,
        model_name=result.model_name,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=result.cost_usd,
        latency_ms=result.latency_ms,
    )
