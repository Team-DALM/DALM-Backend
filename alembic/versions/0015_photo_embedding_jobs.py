"""Add retryable photo embedding jobs.

Revision ID: 0015_photo_embedding_jobs
Revises: 0014_photo_embeddings
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_photo_embedding_jobs"
down_revision: str | None = "0014_photo_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "photo_embedding_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("photo_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(100)),
        sa.Column("error_code", sa.String(50)),
        sa.Column("error_message", sa.String(500)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="photo_embedding_jobs_status_ck",
        ),
        sa.ForeignKeyConstraint(["photo_id"], ["photos.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("photo_id"),
    )
    op.create_index("photo_embedding_jobs_photo_id_ix", "photo_embedding_jobs", ["photo_id"])
    op.create_index("photo_embedding_jobs_status_ix", "photo_embedding_jobs", ["status"])
    op.create_index(
        "photo_embedding_jobs_queue_ix",
        "photo_embedding_jobs",
        ["status", "next_attempt_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("photo_embedding_jobs_queue_ix", table_name="photo_embedding_jobs")
    op.drop_index("photo_embedding_jobs_status_ix", table_name="photo_embedding_jobs")
    op.drop_index("photo_embedding_jobs_photo_id_ix", table_name="photo_embedding_jobs")
    op.drop_table("photo_embedding_jobs")
