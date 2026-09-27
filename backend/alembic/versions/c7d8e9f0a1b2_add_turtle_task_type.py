"""Задание "Черепашка": learningitemtype=TURTLE_TASK (переиспользует learning_items.steps)

Revision ID: c7d8e9f0a1b2
Revises: b8c9d0e1f2a3
Create Date: 2026-09-27

"""
from alembic import op


revision = 'c7d8e9f0a1b2'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE learningitemtype ADD VALUE IF NOT EXISTS 'TURTLE_TASK'")


def downgrade() -> None:
    pass
