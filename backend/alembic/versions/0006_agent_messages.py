"""v2: comunicación directa entre agentes — agent_messages

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-06

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id"), nullable=False
        ),
        sa.Column("from_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("from_agent_name", sa.String(128), nullable=False),
        sa.Column("to_agent", sa.String(128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_agent_messages_run_id", "agent_messages", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_messages_run_id", table_name="agent_messages")
    op.drop_table("agent_messages")
