"""Add users table.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kakao_id", sa.String(length=100), nullable=False),
        sa.Column("nickname", sa.String(length=12), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'RESTRICTED', 'WITHDRAWN')",
            name="users_status_ck",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nickname"),
    )
    op.create_index("users_kakao_id_ix", "users", ["kakao_id"], unique=True)


def downgrade() -> None:
    op.drop_index("users_kakao_id_ix", table_name="users")
    op.drop_table("users")

