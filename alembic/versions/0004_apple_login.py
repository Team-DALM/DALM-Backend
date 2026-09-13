"""Add Apple login identity to users.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "kakao_id", existing_type=sa.String(length=100), nullable=True)
    op.add_column("users", sa.Column("apple_id", sa.String(length=255), nullable=True))
    op.create_index("users_apple_id_ix", "users", ["apple_id"], unique=True)
    op.create_check_constraint(
        "users_social_identity_ck",
        "users",
        "kakao_id IS NOT NULL OR apple_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("users_social_identity_ck", "users", type_="check")
    op.drop_index("users_apple_id_ix", table_name="users")
    op.drop_column("users", "apple_id")
    op.alter_column("users", "kakao_id", existing_type=sa.String(length=100), nullable=False)
