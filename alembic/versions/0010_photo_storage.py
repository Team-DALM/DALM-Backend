"""Add private object storage metadata to photos.

Revision ID: 0010_photo_storage
Revises: 0009_user_profiles
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_photo_storage"
down_revision: str | None = "0009_user_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("photos", sa.Column("storage_key", sa.String(500), nullable=True))
    op.add_column("photos", sa.Column("checksum", sa.String(64), nullable=True))
    op.create_unique_constraint("photos_storage_key_uq", "photos", ["storage_key"])
    op.create_unique_constraint("photos_user_checksum_uq", "photos", ["user_id", "checksum"])


def downgrade() -> None:
    op.drop_constraint("photos_user_checksum_uq", "photos", type_="unique")
    op.drop_constraint("photos_storage_key_uq", "photos", type_="unique")
    op.drop_column("photos", "checksum")
    op.drop_column("photos", "storage_key")
