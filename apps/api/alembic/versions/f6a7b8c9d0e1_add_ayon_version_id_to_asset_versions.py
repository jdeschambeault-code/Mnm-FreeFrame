"""add ayon_version_id to asset_versions, so each delivered version remembers its OWN real Ayon version (not just the asset's first-ever one) - fixes relayed comments always landing on Ayon v001

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-21
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('asset_versions', sa.Column('ayon_version_id', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('asset_versions', 'ayon_version_id')
