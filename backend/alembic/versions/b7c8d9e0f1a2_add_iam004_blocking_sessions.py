"""IAM-004: users.sessions_invalidated_at, login_events

users.is_blocked/created_at/last_login_at НЕ добавляются здесь — они уже
есть в 25112801a2eb (initial schema): та миграция была написана позже, чем
в models.py появились эти поля IAM-004, и авто-сгенерировалась уже с ними.
До этого разрыв был незаметен — все проверки схемы шли через
Base.metadata.create_all() на чистом SQLite (см. README), а не через
настоящий `alembic upgrade head` на Postgres; на первом же реальном прогоне
(деплой на прод, 2026-09-21) это всплыло как DuplicateColumn.

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
    op.add_column('users', sa.Column('sessions_invalidated_at', sa.DateTime(timezone=True), nullable=True))

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
    op.drop_column('users', 'sessions_invalidated_at')
