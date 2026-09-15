"""Add report workflow fields.

Revision ID: 0005_reports_api
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_reports_api"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("detail", sa.Text(), nullable=True))
    op.add_column(
        "reports", sa.Column("status", sa.String(20), server_default="PENDING", nullable=False)
    )
    op.create_unique_constraint(
        "reports_reporter_target_uq", "reports", ["reporter_id", "target_type", "target_id"]
    )


def downgrade() -> None:
    op.drop_constraint("reports_reporter_target_uq", "reports", type_="unique")
    op.drop_column("reports", "status")
    op.drop_column("reports", "detail")
