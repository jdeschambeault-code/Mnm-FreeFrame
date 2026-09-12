"""add google_id to users for Google OAuth login

Revision ID: 9799a0ce2226
Revises: d8e9f0a1b2c3
Create Date: 2026-09-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '9799a0ce2226'
down_revision: Union[str, Sequence[str], None] = 'd8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('google_id', sa.String(length=255), nullable=True))
    op.create_unique_constraint('uq_users_google_id', 'users', ['google_id'])


def downgrade() -> None:
    op.drop_constraint('uq_users_google_id', 'users', type_='unique')
    op.drop_column('users', 'google_id')
