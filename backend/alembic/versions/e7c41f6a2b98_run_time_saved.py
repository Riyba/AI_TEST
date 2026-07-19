"""runs: add user-estimated time_saved_minutes (NULL = not captured)

Revision ID: e7c41f6a2b98
Revises: b3f2a91c7d54
Create Date: 2026-07-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7c41f6a2b98'
down_revision: Union[str, None] = 'b3f2a91c7d54'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('runs') as batch_op:
        batch_op.add_column(
            sa.Column('time_saved_minutes', sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('runs') as batch_op:
        batch_op.drop_column('time_saved_minutes')
