"""IAM-004: users.is_blocked, users.sessions_invalidated_at, users.created_at,
users.last_login_at, login_events

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-09-21

"""
from alembic import op
import sqlalchemy as sa


revision = 'b7c8d9e0f1a2'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_blocked', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('users', sa.Column('sessions_invalidated_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True))
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('users', 'is_blocked', server_default=None)

    op.create_table(
        'login_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_login_events_user_id'), 'login_events', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_login_events_user_id'), table_name='login_events')
    op.drop_table('login_events')
    op.drop_column('users', 'last_login_at')
    op.drop_column('users', 'created_at')
    op.drop_column('users', 'sessions_invalidated_at')
    op.drop_column('users', 'is_blocked')
