"""courses.is_archived — скрыть курс из студии методиста, не трогая publish-статус

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-22

"""
from alembic import op
import sqlalchemy as sa


revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('courses', sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('courses', 'is_archived', server_default=None)


def downgrade() -> None:
    op.drop_column('courses', 'is_archived')
