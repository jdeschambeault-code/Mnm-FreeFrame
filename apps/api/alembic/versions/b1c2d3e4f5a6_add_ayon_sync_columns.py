"""add ayon_project_name to projects and staff_email_domains to instance_settings

Revision ID: b1c2d3e4f5a6
Revises: a9ee0209151a
Create Date: 2026-08-18
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'a9ee0209151a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('ayon_project_name', sa.String(length=255), nullable=True))
    op.create_unique_constraint('uq_projects_ayon_project_name', 'projects', ['ayon_project_name'])
    op.add_column(
        'instance_settings',
        sa.Column(
            'staff_email_domains', sa.JSON(), nullable=False,
            server_default='["mnm.local", "methodnmadness.com"]',
        ),
    )


def downgrade() -> None:
    op.drop_column('instance_settings', 'staff_email_domains')
    op.drop_constraint('uq_projects_ayon_project_name', 'projects', type_='unique')
    op.drop_column('projects', 'ayon_project_name')
