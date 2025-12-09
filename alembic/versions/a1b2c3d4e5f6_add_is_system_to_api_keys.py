"""add is_system to api_keys

Revision ID: a1b2c3d4e5f6
Revises: 2603ecd55436
Create Date: 2025-12-08 22:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '2603ecd55436'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_system column to api_keys table."""
    op.add_column('api_keys', sa.Column('is_system', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    """Remove is_system column from api_keys table."""
    op.drop_column('api_keys', 'is_system')
