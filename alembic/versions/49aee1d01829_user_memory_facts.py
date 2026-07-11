"""user_memory_facts

Creates the `user_memory_facts` table (capstone-round Bundle 3, Req 9-12):
durably-stored freeform facts extracted from past conversations, retrieved
by cosine-similarity search over their embedding for injection into future
chat turns. Enables the `vector` extension (idempotent).

No ANN index (HNSW/ivfflat) on `embedding`: pgvector caps both at 2000
dimensions, but this column is vector(4096) (Task 27's verified
MEMORY_EMBEDDING_DIM) — `CREATE INDEX ... USING hnsw` fails outright at this
width ("column cannot have more than 2000 dimensions for hnsw index",
discovered running Task 38's live-Postgres regression pass; mirrored on
UserMemoryFact.embedding in backend/db/models.py, Task 30). Not a practical
problem: MemoryStore always filters by user_id before ordering by cosine
distance, so an unindexed sequential scan runs over one user's handful of
facts, not the whole table.

Revision ID: 49aee1d01829
Revises: 36703715277c
Create Date: 2026-07-11 12:35:08.926322

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = '49aee1d01829'
down_revision: Union[str, Sequence[str], None] = '36703715277c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "user_memory_facts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("fact_text", sa.String(), nullable=False),
        # Verification spike finding (capstone-round Task 27, recorded 2026-07-11
        # against the live OpenRouter API): settings.embedding_model
        # (qwen/qwen3-embedding-8b) produces 4096-dimensional vectors — vector(4096)
        # width confirmed empirically, not assumed (see
        # .claude/specs/capstone-round/task-27-findings.md). This width is fixed to
        # the EMBEDDING_MODEL configured at migration time; changing EMBEDDING_MODEL
        # later requires a new migration + full re-embed/backfill of existing facts,
        # not just an env var change (mirrored on UserMemoryFact.embedding in
        # backend/db/models.py, Task 30).
        sa.Column("embedding", Vector(4096), nullable=False),
        sa.Column("source_session_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_memory_facts_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_session_id"],
            ["chat_sessions.id"],
            name="fk_user_memory_facts_source_session_id_chat_sessions",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        op.f("ix_user_memory_facts_user_id"), "user_memory_facts", ["user_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("user_memory_facts")
    # `vector` is left installed — other objects may depend on it and it is
    # harmless/idempotent to leave enabled (matches Alembic convention of not
    # reversing CREATE EXTENSION IF NOT EXISTS in downgrade()).
