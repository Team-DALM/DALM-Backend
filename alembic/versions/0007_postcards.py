"""Add postcards.

Revision ID: 0007_postcards
Revises: 0006_notifications
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_postcards"
down_revision: str | None = "0006_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "postcards",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("receiver_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.String(200), nullable=False),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("sender_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("receiver_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("sender_id <> receiver_id", name="postcards_different_users_ck"),
        sa.CheckConstraint("length(trim(content)) BETWEEN 1 AND 200", name="postcards_content_ck"),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"]),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["receiver_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_id", "sender_id"),
        sa.UniqueConstraint("sender_id", "idempotency_key"),
    )
    op.create_index("postcards_receiver_sent_ix", "postcards", ["receiver_id", "sent_at"])
    op.create_index("postcards_sender_sent_ix", "postcards", ["sender_id", "sent_at"])


def downgrade() -> None:
    op.drop_index("postcards_sender_sent_ix", table_name="postcards")
    op.drop_index("postcards_receiver_sent_ix", table_name="postcards")
    op.drop_table("postcards")
