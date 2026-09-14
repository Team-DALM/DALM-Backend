"""Add in-app notifications.

Revision ID: 0006_notifications
Revises: 0005_reports_api
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_notifications"
down_revision: str | None = "0005_reports_api"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=True),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("notifications_user_id_ix", "notifications", ["user_id"])
    op.create_index(
        "notifications_user_created_ix", "notifications", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("notifications_user_created_ix", table_name="notifications")
    op.drop_index("notifications_user_id_ix", table_name="notifications")
    op.drop_table("notifications")
