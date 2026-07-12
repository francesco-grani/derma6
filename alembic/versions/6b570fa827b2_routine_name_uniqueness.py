"""routine_name_uniqueness

Adds a DB-level UniqueConstraint('user_id', 'name') on `routines` as defense
in depth alongside the case-insensitive application-level check added to
ProfileStore.save_routine()/rename_routine() (security-remediation Req
25.1-25.3). This constraint is exact-case, unlike the app-level check — it
exists to catch any write path that bypasses ProfileStore entirely, not to
replace the case-insensitive check.

Revision ID: 6b570fa827b2
Revises: 49aee1d01829
Create Date: 2026-07-12 11:26:58.464073

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '6b570fa827b2'
down_revision: Union[str, Sequence[str], None] = '49aee1d01829'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("routines") as batch_op:
        batch_op.create_unique_constraint("uq_routines_user_id_name", ["user_id", "name"])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("routines") as batch_op:
        batch_op.drop_constraint("uq_routines_user_id_name", type_="unique")
