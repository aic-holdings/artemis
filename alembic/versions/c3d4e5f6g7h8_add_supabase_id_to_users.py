"""Add supabase_id to users table

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2025-12-15

This adds a stable identifier from Jetta SSO/Supabase so users can change
their email without losing access to their Artemis data.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6g7h8'
down_revision = 'b2c3d4e5f6g7'
branch_labels = None
depends_on = None


def upgrade():
    # Add supabase_id column - nullable initially so existing users aren't affected
    op.add_column('users', sa.Column('supabase_id', sa.String(), nullable=True))

    # Create unique index on supabase_id
    op.create_index('ix_users_supabase_id', 'users', ['supabase_id'], unique=True)


def downgrade():
    op.drop_index('ix_users_supabase_id', table_name='users')
    op.drop_column('users', 'supabase_id')
