"""supabase_auth_uuid_pk

UUID primary-key cutover for the Supabase Auth rework (Bundle 2, Req 7.1,
7.2, 7.4). `users.id` switches from a locally-autoincremented integer to a
Supabase-issued UUID string that is always supplied at insert time; every
dependent table's `user_id` foreign key follows the same type change.

This migration is DESTRUCTIVE for any pre-existing rows: an integer `id`
cannot be losslessly mapped onto a Supabase UUID, so `upgrade()` refuses to
run against a non-empty `users` table (Req 7.4) rather than silently
discarding data. See `upgrade()`'s docstring for the required manual
operator step.

Revision ID: e73ee44b73c0
Revises: f154c79309d6
Create Date: 2026-07-10 00:00:00.000000


================================================================================
MIGRATION RUNBOOK — preserving admin status through the cutover (Req 8)
================================================================================

Because Req 7.4 mandates a clean cutover with no preserved data (see the
`RuntimeError` this migration raises against a non-empty `users` table),
"preserving the administrator flag through migration" (Req 8.1) cannot mean
*carrying forward literal rows* — there is nothing to carry forward once the
documented `TRUNCATE` has run. It is instead satisfied procedurally, as an
explicit, manual runbook step — deliberately NOT automated, to avoid a
silent/implicit admin grant on a fresh, unaudited row:

  1. Apply this migration (`alembic upgrade head`) after running the
     documented `TRUNCATE users, routines, routine_steps, chat_sessions,
     introduction_plans, skin_analyses, message_store CASCADE;` (see
     `upgrade()`'s docstring / its `RuntimeError` message).
  2. The previously-admin operator signs up fresh through the new Supabase
     Auth flow, exactly like any other user (email/password + username via
     `/api/auth/complete-signup`). This provisions their `users` row keyed
     by the new Supabase-issued UUID `id`, with `is_admin` defaulting to
     `False` (Req 8.3 — see `backend/db/models.py::User.is_admin`,
     `Mapped[bool] = mapped_column(default=False)`, unchanged by this
     migration).
  3. The operator (or another existing admin, once at least one exists) runs
     a one-off, manual SQL statement directly against the database to
     re-grant admin status, keyed against the NEW UUID `id` (not the old
     integer `id`, which no longer exists post-cutover) via the still-unique
     `username` column (Req 7.3):

         UPDATE users SET is_admin = true WHERE username = '<their username>';

     This satisfies Req 8.1's "preserve the administrator flag ... keyed
     against their post-migration identifier" — the `WHERE` clause resolves
     through `username` (a stable, human-known handle) but the row it
     mutates is addressed by the new UUID primary key underneath.
  4. `is_admin` is read exclusively from this column at request time
     (`backend/api/admin.py::require_admin` does `db.get(User,
     user_id).is_admin`) — it is never derived from the Supabase JWT, which
     carries no application-level role claim at all (Req 8.2). So this
     single manual `UPDATE` is sufficient; there is no separate
     token/claims-side step to perform.

No other admin-status action is required or automated by this migration —
every user, including a former admin, starts as a non-admin after the
cutover until step 3 above is performed by hand.
================================================================================

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e73ee44b73c0'
down_revision: Union[str, Sequence[str], None] = 'f154c79309d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Every table that carries a `user_id` foreign key into `users.id` and must
# be retyped in lockstep with it.
_DEPENDENT_TABLES = ["routines", "chat_sessions", "introduction_plans", "skin_analyses"]


def _drop_fks_referencing_users(inspector: sa.engine.reflection.Inspector) -> None:
    """Drop every FK on a dependent table that references `users.id`.

    Must run before either side of the relationship is retyped: Postgres
    refuses to change a column's type while an incompatible-typed FK still
    references it. Constraints created without an explicit name (as the
    initial migration did) reflect as unnamed on SQLite — there is nothing
    to drop by name there, and SQLite does not enforce FK column-type
    matching at DDL time regardless, so skipping is safe.
    """
    for table_name in _DEPENDENT_TABLES:
        fk_names = [
            fk["name"]
            for fk in inspector.get_foreign_keys(table_name)
            if fk.get("referred_table") == "users" and fk.get("name")
        ]
        if not fk_names:
            continue
        with op.batch_alter_table(table_name) as batch_op:
            for fk_name in fk_names:
                batch_op.drop_constraint(fk_name, type_="foreignkey")


def upgrade() -> None:
    """Upgrade schema.

    Refuses to run against a non-empty `users` table (Req 7.4). An integer
    `id` has no lossless mapping to a Supabase UUID, so this migration will
    not delete or remap existing rows itself. If this raises, an operator
    must first run, deliberately and by hand:

        TRUNCATE users, routines, routine_steps, chat_sessions,
            introduction_plans, skin_analyses, message_store CASCADE;

    then re-run `alembic upgrade head`. `message_store` is the LangGraph
    Postgres checkpointer's table — it is not managed by SQLAlchemy/Alembic
    but must be cleared in the same operation since it also keys off the
    old user/session identifiers.
    """
    bind = op.get_bind()

    count = bind.execute(sa.text("SELECT COUNT(*) FROM users")).scalar()
    if count:
        raise RuntimeError(
            f"Refusing to run the UUID primary-key cutover migration: 'users' "
            f"has {count} existing row(s). This migration changes users.id from "
            "an autoincrementing integer to a Supabase-issued UUID string, which "
            "cannot preserve existing rows losslessly. Manually truncate the "
            "affected tables first, then re-run `alembic upgrade head`:\n\n"
            "    TRUNCATE users, routines, routine_steps, chat_sessions, "
            "introduction_plans, skin_analyses, message_store CASCADE;\n"
        )

    inspector = sa.inspect(bind)

    # 1. Drop FKs referencing users.id so both sides can be retyped
    #    independently without a type mismatch across the constraint.
    _drop_fks_referencing_users(inspector)

    # 2. Retype users.id (drops autoincrement — the PK is always supplied by
    #    Supabase at insert time now); drop password_hash (Supabase owns
    #    credentials); add the new unique/indexed email column (Req 7.1, 7.3).
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "id",
            existing_type=sa.Integer(),
            type_=sa.String(),
            existing_autoincrement=True,
            autoincrement=False,
        )
        batch_op.drop_column("password_hash")
        batch_op.add_column(sa.Column("email", sa.String(), nullable=False))
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    # 3. Retype each dependent table's user_id to match, then re-add the FK
    #    now that both sides share the String type (Req 7.2).
    for table_name in _DEPENDENT_TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                "user_id",
                existing_type=sa.Integer(),
                type_=sa.String(),
            )
            batch_op.create_foreign_key(
                f"fk_{table_name}_user_id_users",
                "users",
                ["user_id"],
                ["id"],
            )


def downgrade() -> None:
    """Downgrade schema.

    Inverse column-type changes. Like `upgrade()`, this assumes the tables
    are empty — a Supabase UUID string has no meaningful mapping back to an
    autoincrementing integer, so downgrading a populated database would
    corrupt `user_id` values just the same as upgrading one would.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. Drop FKs referencing users.id so both sides can be retyped
    #    independently.
    _drop_fks_referencing_users(inspector)

    # 2. Revert each dependent table's user_id back to Integer.
    for table_name in _DEPENDENT_TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                "user_id",
                existing_type=sa.String(),
                type_=sa.Integer(),
            )

    # 3. Revert users.id to an autoincrementing Integer PK; restore
    #    password_hash; drop email.
    op.drop_index(op.f("ix_users_email"), table_name="users")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("email")
        batch_op.add_column(sa.Column("password_hash", sa.String(), nullable=True))
        batch_op.alter_column(
            "id",
            existing_type=sa.String(),
            type_=sa.Integer(),
            existing_autoincrement=False,
            autoincrement=True,
        )

    # 4. Re-add FKs now both sides are Integer again.
    for table_name in _DEPENDENT_TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.create_foreign_key(
                f"fk_{table_name}_user_id_users",
                "users",
                ["user_id"],
                ["id"],
            )
