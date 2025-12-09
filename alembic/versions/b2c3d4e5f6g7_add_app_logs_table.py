"""add app_logs table

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2025-12-08 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create app_logs table for frontend/backend error tracking."""
    op.create_table(
        'app_logs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('level', sa.String(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('error_type', sa.String(), nullable=True),
        sa.Column('stack_trace', sa.Text(), nullable=True),
        sa.Column('page', sa.String(), nullable=True),
        sa.Column('component', sa.String(), nullable=True),
        sa.Column('user_agent', sa.String(), nullable=True),
        sa.Column('extra_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_app_logs_source'), 'app_logs', ['source'], unique=False)
    op.create_index(op.f('ix_app_logs_level'), 'app_logs', ['level'], unique=False)
    op.create_index(op.f('ix_app_logs_error_type'), 'app_logs', ['error_type'], unique=False)
    op.create_index(op.f('ix_app_logs_page'), 'app_logs', ['page'], unique=False)
    op.create_index(op.f('ix_app_logs_created_at'), 'app_logs', ['created_at'], unique=False)


def downgrade() -> None:
    """Remove app_logs table."""
    op.drop_index(op.f('ix_app_logs_created_at'), table_name='app_logs')
    op.drop_index(op.f('ix_app_logs_page'), table_name='app_logs')
    op.drop_index(op.f('ix_app_logs_error_type'), table_name='app_logs')
    op.drop_index(op.f('ix_app_logs_level'), table_name='app_logs')
    op.drop_index(op.f('ix_app_logs_source'), table_name='app_logs')
    op.drop_table('app_logs')
