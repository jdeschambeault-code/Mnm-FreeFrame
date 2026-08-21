"""flip instance_settings.ayon_relay_paused's default to true (paused by default) - a fresh install should not silently start relaying client comments into Ayon before an admin has reviewed the setup

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-21
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('instance_settings', 'ayon_relay_paused', server_default='true')


def downgrade() -> None:
    op.alter_column('instance_settings', 'ayon_relay_paused', server_default='false')
