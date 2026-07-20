"""custom_tools: user-defined tools backed by stored Python source

Revision ID: d5b9e0173a4c
Revises: f4a8c2d91e63
Create Date: 2026-07-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5b9e0173a4c'
down_revision: Union[str, None] = 'f4a8c2d91e63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'custom_tools',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=100), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('input_schema', sa.JSON(), nullable=False),
        sa.Column('mutating', sa.Boolean(), nullable=False),
        sa.Column('source_code', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('custom_tools')
