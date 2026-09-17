"""Add photo validation queue state.

Revision ID: 0012_validation_queue
Revises: 0011_photo_validations
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_validation_queue"
down_revision: str | None = "0011_photo_validations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("photo_validations_status_ck", "photo_validations", type_="check")
    op.create_check_constraint(
        "photo_validations_status_ck",
        "photo_validations",
        "status IN ('PENDING', 'PROCESSING', 'PASSED', 'REJECTED', 'FAILED')",
    )
    op.add_column("photo_validations", sa.Column("worker_id", sa.String(100)))
    op.add_column("photo_validations", sa.Column("error_code", sa.String(50)))
    op.add_column("photo_validations", sa.Column("error_message", sa.String(500)))
    op.add_column(
        "photo_validations", sa.Column("next_attempt_at", sa.DateTime(timezone=True))
    )
    op.add_column("photo_validations", sa.Column("started_at", sa.DateTime(timezone=True)))
    op.create_index(
        "photo_validations_queue_ix",
        "photo_validations",
        ["status", "next_attempt_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("photo_validations_queue_ix", table_name="photo_validations")
    op.drop_column("photo_validations", "started_at")
    op.drop_column("photo_validations", "next_attempt_at")
    op.drop_column("photo_validations", "error_message")
    op.drop_column("photo_validations", "error_code")
    op.drop_column("photo_validations", "worker_id")
    op.drop_constraint("photo_validations_status_ck", "photo_validations", type_="check")
    op.create_check_constraint(
        "photo_validations_status_ck",
        "photo_validations",
        "status IN ('PENDING', 'PASSED', 'REJECTED', 'FAILED')",
    )
