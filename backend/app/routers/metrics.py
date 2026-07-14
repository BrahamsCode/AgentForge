import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Agent, Run, TraceStep, User
from app.security import get_current_user
from app.tenancy.deps import get_active_org
from app.tenancy.models import Organization

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


class CostByAgent(BaseModel):
    agent_id: uuid.UUID | None
    agent_name: str | None
    cost_usd: float
    tokens: int
    steps: int


class ToolUsage(BaseModel):
    tool: str
    count: int


class MetricsSummary(BaseModel):
    runs_total: int
    runs_completed: int
    runs_failed: int
    success_rate: float
    total_cost_usd: float
    total_tokens: int
    avg_steps_per_run: float
    cost_by_agent: list[CostByAgent]
    top_tools: list[ToolUsage]


@router.get("/costs", response_model=MetricsSummary)
async def costs(
    since_days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
    org: Organization | None = Depends(get_active_org),
) -> MetricsSummary:
    since = datetime.now(UTC) - timedelta(days=since_days)
    org_id = org.id if org else None  # métricas scopeadas a la organización activa

    status_rows = (
        await db.execute(
            select(Run.status, func.count(), func.coalesce(func.sum(Run.total_cost_usd), 0.0),
                   func.coalesce(func.sum(Run.total_tokens), 0))
            .where(Run.created_at >= since, Run.org_id == org_id)
            .group_by(Run.status)
        )
    ).all()
    by_status = {s: (c, cost, tok) for s, c, cost, tok in status_rows}
    runs_total = sum(c for c, _, _ in by_status.values())
    runs_completed = by_status.get("completed", (0, 0, 0))[0]
    runs_failed = by_status.get("failed", (0, 0, 0))[0]
    total_cost = sum(cost for _, cost, _ in by_status.values())
    total_tokens = sum(tok for _, _, tok in by_status.values())

    # Costo por agente (vía trace_steps para atribuir por agente en runs de equipo)
    agent_rows = (
        await db.execute(
            select(
                TraceStep.agent_id, Agent.name,
                func.coalesce(func.sum(TraceStep.cost_usd), 0.0),
                func.coalesce(func.sum(TraceStep.tokens_in + TraceStep.tokens_out), 0),
                func.count(),
            )
            .join(Run, Run.id == TraceStep.run_id)
            .outerjoin(Agent, Agent.id == TraceStep.agent_id)
            .where(Run.created_at >= since, Run.org_id == org_id)
            .group_by(TraceStep.agent_id, Agent.name)
            .order_by(func.sum(TraceStep.cost_usd).desc())
        )
    ).all()
    cost_by_agent = [
        CostByAgent(agent_id=aid, agent_name=name, cost_usd=round(cost, 6), tokens=tok, steps=steps)
        for aid, name, cost, tok, steps in agent_rows
    ]

    # Herramientas más usadas
    tool_rows = (
        await db.execute(
            select(TraceStep.input["tool"].astext, func.count())
            .join(Run, Run.id == TraceStep.run_id)
            .where(TraceStep.kind == "tool_call", Run.created_at >= since, Run.org_id == org_id)
            .group_by(TraceStep.input["tool"].astext)
            .order_by(func.count().desc())
            .limit(10)
        )
    ).all()
    top_tools = [ToolUsage(tool=t or "?", count=c) for t, c in tool_rows]

    total_steps = (
        await db.scalar(
            select(func.count())
            .select_from(TraceStep)
            .join(Run, Run.id == TraceStep.run_id)
            .where(Run.created_at >= since, Run.org_id == org_id)
        )
    ) or 0

    return MetricsSummary(
        runs_total=runs_total,
        runs_completed=runs_completed,
        runs_failed=runs_failed,
        success_rate=round(runs_completed / runs_total, 3) if runs_total else 0.0,
        total_cost_usd=round(total_cost, 6),
        total_tokens=total_tokens,
        avg_steps_per_run=round(total_steps / runs_total, 1) if runs_total else 0.0,
        cost_by_agent=cost_by_agent,
        top_tools=top_tools,
    )
