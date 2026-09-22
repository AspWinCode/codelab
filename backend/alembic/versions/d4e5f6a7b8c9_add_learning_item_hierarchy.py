"""Иерархия дерева курса (module/submodule/topic/subtopic) и learning_items.is_archived

Значения enum добавляются вне транзакции (autocommit_block) — Postgres не
позволяет ALTER TYPE ... ADD VALUE внутри той же транзакции, где новое
значение уже может использоваться.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-22

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


NEW_VALUES = ("MODULE", "SUBMODULE", "TOPIC", "SUBTOPIC")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for value in NEW_VALUES:
            op.execute(f"ALTER TYPE learningitemtype ADD VALUE IF NOT EXISTS '{value}'")

    op.add_column('learning_items', sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('learning_items', 'is_archived', server_default=None)


def downgrade() -> None:
    # Postgres не поддерживает удаление значений enum — оставляем их,
    # откатываем только колонку.
    op.drop_column('learning_items', 'is_archived')
