"""runs: add synced_to_datadog (True once metrics were accepted by Datadog)

Revision ID: f4a8c2d91e63
Revises: a91d3e5f8c02
Create Date: 2026-07-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f4a8c2d91e63'
down_revision: Union[str, None] = 'a91d3e5f8c02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('runs') as batch_op:
        batch_op.add_column(
            sa.Column(
                'synced_to_datadog',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('runs') as batch_op:
        batch_op.drop_column('synced_to_datadog')
