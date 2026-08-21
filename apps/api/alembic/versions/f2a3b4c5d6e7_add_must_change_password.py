"""add must_change_password to users, forcing a password reset after admin-created accounts (POST /admin/users)

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('users', 'must_change_password')
