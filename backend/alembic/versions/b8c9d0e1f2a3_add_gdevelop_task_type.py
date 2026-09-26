"""GDevelop-задание: learningitemtype=GDEVELOP_TASK (переиспользует learning_items.steps)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-27

"""
from alembic import op


revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE learningitemtype ADD VALUE IF NOT EXISTS 'GDEVELOP_TASK'")


def downgrade() -> None:
    pass
