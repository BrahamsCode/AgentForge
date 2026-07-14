"""v2: scoping por organización — org_id en agents y runs

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-06

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("agents", "runs"):
        op.add_column(
            table,
            sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_index(f"ix_{table}_org_id", table, ["org_id"])


def downgrade() -> None:
    for table in ("agents", "runs"):
        op.drop_index(f"ix_{table}_org_id", table_name=table)
        op.drop_column(table, "org_id")
