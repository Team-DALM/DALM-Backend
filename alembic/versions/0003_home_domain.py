"""Add photo and match tables used by the home APIs.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("image_url", sa.String(length=2048), nullable=False),
        sa.Column("ai_title", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("registered_date", sa.Date(), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("search_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_code", sa.String(length=50), nullable=True),
        sa.Column("rejection_message", sa.String(length=200), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('VALIDATING', 'REJECTED', 'SEARCHING', 'MATCHED', 'EXPIRED', 'DELETED')",
            name="photos_status_ck",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("photos_user_id_ix", "photos", ["user_id"])
    op.create_index("photos_status_ix", "photos", ["status"])
    op.create_index("photos_registered_date_ix", "photos", ["registered_date"])
    op.create_index(
        "photos_one_active_per_day_uq",
        "photos",
        ["user_id", "registered_date"],
        unique=True,
        postgresql_where=sa.text("status IN ('VALIDATING', 'SEARCHING', 'MATCHED', 'EXPIRED')"),
    )

    op.create_table(
        "matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "matched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "match_participants",
        sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("photo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"]),
        sa.ForeignKeyConstraint(["photo_id"], ["photos.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("match_id", "user_id"),
        sa.UniqueConstraint("photo_id"),
    )
    op.create_index("match_participants_user_id_ix", "match_participants", ["user_id"])

    op.create_table(
        "blocks",
        sa.Column("blocker_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blocked_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("blocker_id <> blocked_id", name="blocks_different_users_ck"),
        sa.ForeignKeyConstraint(["blocked_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["blocker_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("blocker_id", "blocked_id"),
    )
    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reporter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason_code", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "target_type IN ('PHOTO', 'POSTCARD', 'USER')", name="reports_target_type_ck"
        ),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("reports_reporter_id_ix", "reports", ["reporter_id"])
    op.create_index("reports_target_id_ix", "reports", ["target_id"])


def downgrade() -> None:
    op.drop_index("reports_target_id_ix", table_name="reports")
    op.drop_index("reports_reporter_id_ix", table_name="reports")
    op.drop_table("reports")
    op.drop_table("blocks")
    op.drop_index("match_participants_user_id_ix", table_name="match_participants")
    op.drop_table("match_participants")
    op.drop_table("matches")
    op.drop_index("photos_one_active_per_day_uq", table_name="photos")
    op.drop_index("photos_registered_date_ix", table_name="photos")
    op.drop_index("photos_status_ix", table_name="photos")
    op.drop_index("photos_user_id_ix", table_name="photos")
    op.drop_table("photos")
