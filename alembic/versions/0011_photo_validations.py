"""Add photo validation jobs.

Revision ID: 0011_photo_validations
Revises: 0010_photo_storage
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_photo_validations"
down_revision: str | None = "0010_photo_storage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "photo_validations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("photo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=True),
        sa.Column("rejection_code", sa.String(50), nullable=True),
        sa.Column("model_name", sa.String(100), nullable=True),
        sa.Column("model_version", sa.String(50), nullable=True),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PASSED', 'REJECTED', 'FAILED')",
            name="photo_validations_status_ck",
        ),
        sa.ForeignKeyConstraint(["photo_id"], ["photos.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("photo_id"),
    )
    op.create_index("photo_validations_photo_id_ix", "photo_validations", ["photo_id"])
    op.create_index("photo_validations_status_ix", "photo_validations", ["status"])


def downgrade() -> None:
    op.drop_index("photo_validations_status_ix", table_name="photo_validations")
    op.drop_index("photo_validations_photo_id_ix", table_name="photo_validations")
    op.drop_table("photo_validations")
