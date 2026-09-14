"""Add user profiles and term agreements.

Revision ID: 0009_user_profiles
Revises: 0008_notification_preferences
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_user_profiles"
down_revision: str | None = "0008_notification_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("profile_image_key", sa.String(500), nullable=True))
    op.add_column("users", sa.Column("bio", sa.String(100), nullable=True))
    op.add_column(
        "users",
        sa.Column("marketing_agreed", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "user_terms",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("term_type", sa.String(30), nullable=False),
        sa.Column("term_version", sa.String(20), nullable=False),
        sa.Column("agreed", sa.Boolean(), nullable=False),
        sa.Column("agreed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "term_type", "term_version"),
    )
    op.create_index("user_terms_user_id_ix", "user_terms", ["user_id"])


def downgrade() -> None:
    op.drop_index("user_terms_user_id_ix", table_name="user_terms")
    op.drop_table("user_terms")
    op.drop_column("users", "marketing_agreed")
    op.drop_column("users", "bio")
    op.drop_column("users", "profile_image_key")
