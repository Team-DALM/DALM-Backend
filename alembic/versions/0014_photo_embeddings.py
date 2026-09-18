"""Add model-agnostic photo embeddings.

Revision ID: 0014_photo_embeddings
Revises: 0013_postcard_replies
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0014_photo_embeddings"
down_revision: str | None = "0013_postcard_replies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "photo_embeddings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("photo_id", sa.UUID(), nullable=False),
        sa.Column("scene_vector", VECTOR(), nullable=False),
        sa.Column("object_action_vector", VECTOR(), nullable=False),
        sa.Column("composition_vector", VECTOR(), nullable=False),
        sa.Column("color_vector", VECTOR(), nullable=False),
        sa.Column("mood_vector", VECTOR(), nullable=False),
        sa.Column("labels", JSONB(), nullable=True),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["photo_id"], ["photos.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("photo_id"),
    )
    op.create_index(
        "photo_embeddings_photo_id_ix",
        "photo_embeddings",
        ["photo_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("photo_embeddings_photo_id_ix", table_name="photo_embeddings")
    op.drop_table("photo_embeddings")
