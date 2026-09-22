"""Snap!-задание: тип learningitemtype=SNAP_TASK и learning_items.steps

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-22

"""
from alembic import op
import sqlalchemy as sa


revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE learningitemtype ADD VALUE IF NOT EXISTS 'SNAP_TASK'")

    op.add_column('learning_items', sa.Column('steps', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('learning_items', 'steps')
