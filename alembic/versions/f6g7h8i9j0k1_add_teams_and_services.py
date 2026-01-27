"""add teams and services

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-01-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6g7h8i9j0k1'
down_revision: Union[str, None] = 'e5f6g7h8i9j0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ===========================================
    # CREATE NEW TABLES
    # ===========================================

    # Teams - groups of people within an organization
    op.create_table(
        'teams',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='active'),
        sa.Column('created_by_user_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_teams_org'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], name='fk_teams_created_by'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'name', name='unique_org_team_name')
    )
    op.create_index('ix_teams_organization_id', 'teams', ['organization_id'])

    # Team members - pivot table for users in teams
    op.create_table(
        'team_members',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('team_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False, server_default='member'),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('added_by_user_id', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], name='fk_team_members_team'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_team_members_user'),
        sa.ForeignKeyConstraint(['added_by_user_id'], ['users.id'], name='fk_team_members_added_by'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('team_id', 'user_id', name='unique_team_member')
    )
    op.create_index('ix_team_members_team_id', 'team_members', ['team_id'])
    op.create_index('ix_team_members_user_id', 'team_members', ['user_id'])

    # Services - applications that call LLMs
    op.create_table(
        'services',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('team_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='active'),
        sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('suspended_reason', sa.Text(), nullable=True),
        sa.Column('suspended_by_user_id', sa.String(), nullable=True),
        sa.Column('alert_threshold_cents', sa.Integer(), nullable=True),
        sa.Column('monthly_budget_cents', sa.Integer(), nullable=True),
        sa.Column('created_by_user_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_services_org'),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], name='fk_services_team'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], name='fk_services_created_by'),
        sa.ForeignKeyConstraint(['suspended_by_user_id'], ['users.id'], name='fk_services_suspended_by'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'name', name='unique_org_service_name')
    )
    op.create_index('ix_services_organization_id', 'services', ['organization_id'])
    op.create_index('ix_services_team_id', 'services', ['team_id'])

    # ===========================================
    # ADD COLUMNS TO EXISTING TABLES
    # ===========================================

    # api_keys - add service_id, environment, expires_at, rotation_group_id
    op.add_column('api_keys', sa.Column('service_id', sa.String(), nullable=True))
    op.add_column('api_keys', sa.Column('environment', sa.String(), nullable=True))
    op.add_column('api_keys', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('api_keys', sa.Column('rotation_group_id', sa.String(), nullable=True))
    op.create_foreign_key('fk_api_keys_service', 'api_keys', 'services', ['service_id'], ['id'])
    op.create_index('ix_api_keys_service_id', 'api_keys', ['service_id'])
    op.create_index('ix_api_keys_rotation_group_id', 'api_keys', ['rotation_group_id'])

    # usage_logs - add denormalized snapshots (NO foreign keys - these are snapshots)
    op.add_column('usage_logs', sa.Column('service_id', sa.String(), nullable=True))
    op.add_column('usage_logs', sa.Column('team_id_at_request', sa.String(), nullable=True))
    op.add_column('usage_logs', sa.Column('api_key_created_by_user_id', sa.String(), nullable=True))
    op.create_index('ix_usage_logs_service_id', 'usage_logs', ['service_id'])
    op.create_index('ix_usage_logs_team_id_at_request', 'usage_logs', ['team_id_at_request'])
    op.create_index('ix_usage_logs_api_key_created_by_user_id', 'usage_logs', ['api_key_created_by_user_id'])


def downgrade() -> None:
    # Drop columns from usage_logs
    op.drop_index('ix_usage_logs_api_key_created_by_user_id', 'usage_logs')
    op.drop_index('ix_usage_logs_team_id_at_request', 'usage_logs')
    op.drop_index('ix_usage_logs_service_id', 'usage_logs')
    op.drop_column('usage_logs', 'api_key_created_by_user_id')
    op.drop_column('usage_logs', 'team_id_at_request')
    op.drop_column('usage_logs', 'service_id')

    # Drop columns from api_keys
    op.drop_index('ix_api_keys_rotation_group_id', 'api_keys')
    op.drop_index('ix_api_keys_service_id', 'api_keys')
    op.drop_constraint('fk_api_keys_service', 'api_keys', type_='foreignkey')
    op.drop_column('api_keys', 'rotation_group_id')
    op.drop_column('api_keys', 'expires_at')
    op.drop_column('api_keys', 'environment')
    op.drop_column('api_keys', 'service_id')

    # Drop new tables (in reverse order due to foreign keys)
    op.drop_index('ix_services_team_id', 'services')
    op.drop_index('ix_services_organization_id', 'services')
    op.drop_table('services')

    op.drop_index('ix_team_members_user_id', 'team_members')
    op.drop_index('ix_team_members_team_id', 'team_members')
    op.drop_table('team_members')

    op.drop_index('ix_teams_organization_id', 'teams')
    op.drop_table('teams')
