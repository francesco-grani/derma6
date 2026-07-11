"""drop_username_uniqueness

`username` becomes a plain, non-unique display name (e.g. the user's first
name, used only when the AI/UI addresses them) rather than an identifier.
Drops the unique index `ix_users_username` added by the initial migration;
the column itself is untouched (still `NOT NULL` — still a required field
at signup, just no longer unique).

Revision ID: 36703715277c
Revises: e73ee44b73c0
Create Date: 2026-07-11 10:19:18.918316

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '36703715277c'
down_revision: Union[str, Sequence[str], None] = 'e73ee44b73c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index(op.f("ix_users_username"), table_name="users")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
