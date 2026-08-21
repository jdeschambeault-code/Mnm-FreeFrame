"""add user_hidden_projects table, for staff users to personally hide a project from their own list

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-08-18
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, Sequence[str], None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_hidden_projects',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('hidden_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('user_id', 'project_id', name='uq_user_hidden_projects_user_project'),
    )
    op.create_index('ix_user_hidden_projects_user_id', 'user_hidden_projects', ['user_id'])
    op.create_index('ix_user_hidden_projects_project_id', 'user_hidden_projects', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_user_hidden_projects_project_id', table_name='user_hidden_projects')
    op.drop_index('ix_user_hidden_projects_user_id', table_name='user_hidden_projects')
    op.drop_table('user_hidden_projects')
