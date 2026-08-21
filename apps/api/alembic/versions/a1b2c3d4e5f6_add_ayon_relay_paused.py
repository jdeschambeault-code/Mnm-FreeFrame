"""add ayon_relay_paused to instance_settings, a global pause/resume switch for scripts/ayon_relay.py's automatic relaying

Revision ID: a1b2c3d4e5f6
Revises: f2a3b4c5d6e7
Create Date: 2026-08-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'instance_settings',
        sa.Column('ayon_relay_paused', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('instance_settings', 'ayon_relay_paused')
