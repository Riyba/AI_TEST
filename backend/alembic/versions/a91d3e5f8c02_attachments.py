"""attachments: files attached to agents or runs, fed to agent LLM calls

Revision ID: a91d3e5f8c02
Revises: e7c41f6a2b98
Create Date: 2026-07-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a91d3e5f8c02'
down_revision: Union[str, None] = 'e7c41f6a2b98'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'attachments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('agent_id', sa.Integer(), sa.ForeignKey('agents.id'), nullable=True),
        sa.Column('run_id', sa.Integer(), sa.ForeignKey('runs.id'), nullable=True),
        sa.Column('filename', sa.String(length=300), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('attachments')
