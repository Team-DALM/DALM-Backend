"""Allow alternating postcard replies.

Revision ID: 0013_postcard_replies
Revises: 0012_validation_queue
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_postcard_replies"
down_revision: str | None = "0012_validation_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("postcards_match_id_sender_id_key", "postcards", type_="unique")
    op.create_index(
        "postcards_match_sent_ix",
        "postcards",
        ["match_id", sa.text("sent_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("postcards_match_sent_ix", table_name="postcards")
    op.create_unique_constraint(
        "postcards_match_id_sender_id_key", "postcards", ["match_id", "sender_id"]
    )
