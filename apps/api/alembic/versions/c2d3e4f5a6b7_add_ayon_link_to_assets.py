"""add ayon origin linkage to assets, for client-delivery ingestion

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-08-18
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('assets', sa.Column('ayon_project_name', sa.String(length=255), nullable=True))
    op.add_column('assets', sa.Column('ayon_folder_id', sa.String(length=64), nullable=True))
    op.add_column('assets', sa.Column('ayon_task_id', sa.String(length=64), nullable=True))
    op.add_column('assets', sa.Column('ayon_version_id', sa.String(length=64), nullable=True))
    op.create_index('ix_assets_ayon_folder_id', 'assets', ['ayon_folder_id'])


def downgrade() -> None:
    op.drop_index('ix_assets_ayon_folder_id', table_name='assets')
    op.drop_column('assets', 'ayon_version_id')
    op.drop_column('assets', 'ayon_task_id')
    op.drop_column('assets', 'ayon_folder_id')
    op.drop_column('assets', 'ayon_project_name')
