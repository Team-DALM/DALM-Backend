"""Add device tokens and notification settings.

Revision ID: 0008_notification_preferences
Revises: 0007_postcards
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_notification_preferences"
down_revision: str | None = "0007_postcards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.String(512), nullable=False),
        sa.Column("platform", sa.String(10), nullable=False),
        sa.Column(
            "last_used_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("device_tokens_user_id_ix", "device_tokens", ["user_id"])
    op.create_table(
        "notification_settings",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("validation_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("match_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("postcard_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("search_expired_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("system_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("notification_settings")
    op.drop_index("device_tokens_user_id_ix", table_name="device_tokens")
    op.drop_table("device_tokens")
