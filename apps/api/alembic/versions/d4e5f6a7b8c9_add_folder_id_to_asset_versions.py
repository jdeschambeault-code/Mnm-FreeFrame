"""add folder_id to asset_versions, so a version can live in a different folder than its asset's primary one (e.g. per-delivery-date folders that still share one asset for Compare Versions)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-21
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('asset_versions', sa.Column('folder_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index('ix_asset_versions_folder_id', 'asset_versions', ['folder_id'])
    op.create_foreign_key(
        'fk_asset_versions_folder_id', 'asset_versions', 'folders', ['folder_id'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_asset_versions_folder_id', 'asset_versions', type_='foreignkey')
    op.drop_index('ix_asset_versions_folder_id', table_name='asset_versions')
    op.drop_column('asset_versions', 'folder_id')
