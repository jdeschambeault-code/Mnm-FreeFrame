"""add client_share_expiry_days/enforced and client_share_watermark_enforced to instance_settings, the admin-configurable default+lock rules applied to non-staff-created share links

Revision ID: d8e9f0a1b2c3
Revises: f6a7b8c9d0e1
Create Date: 2026-08-25
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'instance_settings',
        sa.Column('client_share_expiry_days', sa.Integer(), nullable=False, server_default='7'),
    )
    op.add_column(
        'instance_settings',
        sa.Column('client_share_expiry_enforced', sa.Boolean(), nullable=False, server_default='true'),
    )
    op.add_column(
        'instance_settings',
        sa.Column('client_share_watermark_enforced', sa.Boolean(), nullable=False, server_default='true'),
    )


def downgrade() -> None:
    op.drop_column('instance_settings', 'client_share_watermark_enforced')
    op.drop_column('instance_settings', 'client_share_expiry_enforced')
    op.drop_column('instance_settings', 'client_share_expiry_days')
