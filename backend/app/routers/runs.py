import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Agent, Approval, Run, TraceStep, User
from app.security import get_current_user
from app.sse import get_user_from_header_or_query, run_event_stream
from app.tenancy.deps import enforce_daily_limits, get_active_org
from app.tenancy.models import Organization

router = APIRouter(prefix="/api/runs", tags=["runs"])

_TERMINAL = ("completed", "failed", "cancelled")


class RunCreate(BaseModel):
    agent_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    goal: str = Field(min_length=1, max_length=50_000)
    schedule_cron: str | None = None  # si se envía, crea una plantilla programada
    webhook_url: str | None = None  # notificación al terminar cada run (CU-3)
    mode: str | None = None  # "swarm" (v2): N clones compiten y un juez elige


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID | None
    team_id: uuid.UUID | None
    goal: str
    status: str
    error: str | None
    total_cost_usd: float
    total_tokens: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    final_answer: str | None = None

    @classmethod
    def from_run(cls, run: Run) -> "RunOut":
        out = cls.model_validate(run)
        if run.checkpoint:
            out.final_answer = run.checkpoint.get("final_answer")
        return out


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    action_summary: str
    status: str
    created_at: datetime
    decided_at: datetime | None


class ApprovalDecision(BaseModel):
    approval_id: uuid.UUID
    decision: str  # approved | rejected


class TraceStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    step_number: int
    kind: str
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    created_at: datetime


async def _get_run_or_404(run_id: uuid.UUID, db: AsyncSession) -> Run:
    run = await db.scalar(select(Run).where(Run.id == run_id))
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run no encontrado")
    return run


@router.post("", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def create_run(
    body: RunCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    org: Organization | None = Depends(get_active_org),
) -> RunOut:
    if (body.agent_id is None) == (body.team_id is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Envía exactamente uno: agent_id o team_id"
        )

    if org is not None:
        await enforce_daily_limits(db, org)

    if body.agent_id is not None:
        agent = await db.scalar(select(Agent).where(Agent.id == body.agent_id))
        if agent is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agente no encontrado")
    else:
        from app.models import Team

        team = await db.scalar(select(Team).where(Team.id == body.team_id))
        if team is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Equipo no encontrado")

    if body.mode is not None and body.mode != "swarm":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "mode solo admite 'swarm'")
    if body.mode == "swarm" and body.agent_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El modo swarm requiere agent_id")

    extra: dict = {}
    if body.webhook_url:
        extra["notify"] = {"webhook_url": body.webhook_url}
    if body.mode == "swarm":
        extra["mode"] = "swarm"

    if body.schedule_cron:
        # Validación del cron y creación de plantilla (no se encola).
        from app.scheduler.cron import parse_cron

        try:
            parse_cron(body.schedule_cron)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Cron inválido: {exc}")
        run = Run(
            agent_id=body.agent_id, team_id=body.team_id, goal=body.goal,
            status="scheduled", schedule_cron=body.schedule_cron,
            checkpoint=extra or None, created_by=user.id, org_id=org.id if org else None,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return RunOut.from_run(run)

    run = Run(
        agent_id=body.agent_id, team_id=body.team_id, goal=body.goal,
        status="queued", checkpoint=extra or None,
        created_by=user.id, org_id=org.id if org else None,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    from app.queue.bus import enqueue_run

    await enqueue_run(str(run.id))
    return RunOut.from_run(run)


@router.get("", response_model=list[RunOut])
async def list_runs(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
    org: Organization | None = Depends(get_active_org),
) -> list[RunOut]:
    result = await db.scalars(
        select(Run)
        .where(Run.org_id == (org.id if org else None))
        .order_by(Run.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return [RunOut.from_run(r) for r in result]


@router.get("/{run_id}", response_model=RunOut)
async def get_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> RunOut:
    return RunOut.from_run(await _get_run_or_404(run_id, db))


@router.get("/{run_id}/trace", response_model=list[TraceStepOut])
async def get_trace(
    run_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[TraceStep]:
    await _get_run_or_404(run_id, db)
    result = await db.scalars(
        select(TraceStep)
        .where(TraceStep.run_id == run_id)
        .order_by(TraceStep.step_number)
        .offset(offset)
        .limit(limit)
    )
    return list(result)


@router.post("/{run_id}/cancel", response_model=RunOut)
async def cancel_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> RunOut:
    run = await _get_run_or_404(run_id, db)
    if run.status in _TERMINAL:
        raise HTTPException(status.HTTP_409_CONFLICT, f"El run ya está {run.status}")

    run.status = "cancelled"
    run.finished_at = datetime.now(UTC)
    await db.commit()

    from app.queue.bus import publish_event

    await publish_event(str(run.id), {"type": "run_cancelled", "run_id": str(run.id)})
    return RunOut.from_run(run)


@router.get("/{run_id}/approvals", response_model=list[ApprovalOut])
async def list_approvals(
    run_id: uuid.UUID,
    only_pending: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Approval]:
    await _get_run_or_404(run_id, db)
    query = select(Approval).where(Approval.run_id == run_id)
    if only_pending:
        query = query.where(Approval.status == "pending")
    result = await db.scalars(query.order_by(Approval.created_at))
    return list(result)


@router.post("/{run_id}/approve", response_model=ApprovalOut)
async def decide_approval(
    run_id: uuid.UUID,
    body: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Approval:
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "decision debe ser approved|rejected")
    approval = await db.scalar(
        select(Approval).where(Approval.id == body.approval_id, Approval.run_id == run_id)
    )
    if approval is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aprobación no encontrada")
    if approval.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"La aprobación ya está {approval.status}")

    approval.status = body.decision
    approval.decided_by = user.id
    approval.decided_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(approval)
    return approval


@router.get("/{run_id}/events")
async def run_events(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_user_from_header_or_query),
) -> StreamingResponse:
    run = await _get_run_or_404(run_id, db)
    return StreamingResponse(
        run_event_stream(str(run_id), run_is_terminal=run.status in _TERMINAL),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
