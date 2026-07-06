import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TeamTemplate(Base):
    """Plantilla reutilizable de equipo (marketplace, backlog v2).

    Aditivo respecto a app.models: guarda la definición de un equipo
    preconfigurado (orquestador + miembros) en `spec` como JSON. Al
    instanciarla se materializan Agent/Team/TeamMember reales.

    Forma de `spec`::

        {
          "orchestrator": {
            "name", "role", "model_provider", "model_name",
            "system_prompt", "max_steps", "max_cost_usd"
          },
          "members": [
            {..mismos campos.., "specialty": str},
            ...
          ]
        }
    """

    __tablename__ = "team_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(64), default="general")
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
