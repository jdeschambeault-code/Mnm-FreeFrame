"""add ayon_url/ayon_api_key override columns to instance_settings, so Settings > Admin > Ayon Projects can repoint/rotate the Ayon connection without restarting the launcher

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('instance_settings', sa.Column('ayon_url', sa.String(500), nullable=True))
    op.add_column('instance_settings', sa.Column('ayon_api_key', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('instance_settings', 'ayon_api_key')
    op.drop_column('instance_settings', 'ayon_url')
