"""add workspace_name to instance_settings, backing Settings > Branding > Workspace name server-side so it can be used as the {{site_name}} email variable

Revision ID: e1f2a3b4c5d6
Revises: d3e4f5a6b7c8
Create Date: 2026-08-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'instance_settings',
        sa.Column('workspace_name', sa.String(255), nullable=False, server_default='FreeFrame'),
    )


def downgrade() -> None:
    op.drop_column('instance_settings', 'workspace_name')
