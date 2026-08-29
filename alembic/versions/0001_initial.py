"""Initialize DALM database schema.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Reserve the initial migration boundary before domain tables are added."""


def downgrade() -> None:
    """The initial migration does not create database objects."""

