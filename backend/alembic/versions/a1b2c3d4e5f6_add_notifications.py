"""add notifications, notification_preferences, enrollment.deadline_notified_at

Revision ID: a1b2c3d4e5f6
Revises: 2da621bab1df
Create Date: 2026-09-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'a1b2c3d4e5f6'
down_revision = '2da621bab1df'
branch_labels = None
depends_on = None

# Тип общий для двух таблиц ниже — create_type=False на колонках, тип
# создаём явно один раз сами, иначе второй create_table попытается
# CREATE TYPE notificationtype повторно и упадёт на Postgres.
notification_type_enum = postgresql.ENUM(
    'COURSE_ASSIGNED', 'DEADLINE_APPROACHING', 'MANUAL_REVIEW_RESULT',
    name='notificationtype', create_type=False,
)


def upgrade() -> None:
    notification_type_enum.create(op.get_bind(), checkfirst=True)

    op.add_column('enrollments', sa.Column('deadline_notified_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('type', notification_type_enum, nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)

    op.create_table(
        'notification_preferences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('type', notification_type_enum, nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'type', name='uq_user_notification_type'),
    )
    op.create_index(op.f('ix_notification_preferences_user_id'), 'notification_preferences', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_notification_preferences_user_id'), table_name='notification_preferences')
    op.drop_table('notification_preferences')
    op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_column('enrollments', 'deadline_notified_at')
    notification_type_enum.drop(op.get_bind(), checkfirst=True)
