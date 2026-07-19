"""agent run limits: drop temperature, add max_turns / max_tokens

Revision ID: b3f2a91c7d54
Revises: c876dcb5b44b
Create Date: 2026-07-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3f2a91c7d54'
down_revision: Union[str, None] = 'c876dcb5b44b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('agents') as batch_op:
        batch_op.add_column(
            sa.Column('max_turns', sa.Integer(), nullable=False, server_default='10')
        )
        batch_op.add_column(
            sa.Column('max_tokens', sa.Integer(), nullable=False, server_default='100000')
        )
        batch_op.drop_column('temperature')

    # Backfill already-seeded template agents with the same per-agent limits
    # that fresh seeds get (see app/templates.py). Everyone else keeps the
    # server defaults (10 / 100000).
    seeded_limits = {
        'Code Reviewer': (15, 150_000),
        'Test Writer': (12, 120_000),
        'PR Description Writer': (8, 80_000),
        'Dependency Auditor': (12, 120_000),
        'Refactor Advisor': (12, 120_000),
        'Test Failure Debugger': (12, 120_000),
        'Summarizer (fast)': (2, 20_000),
    }
    conn = op.get_bind()
    for name, (turns, tokens) in seeded_limits.items():
        conn.execute(
            sa.text(
                'UPDATE agents SET max_turns = :turns, max_tokens = :tokens '
                'WHERE name = :name AND is_template = 1'
            ),
            {'turns': turns, 'tokens': tokens, 'name': name},
        )


def downgrade() -> None:
    with op.batch_alter_table('agents') as batch_op:
        batch_op.add_column(sa.Column('temperature', sa.Float(), nullable=True))
        batch_op.drop_column('max_tokens')
        batch_op.drop_column('max_turns')
