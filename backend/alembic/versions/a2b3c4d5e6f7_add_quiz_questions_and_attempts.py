"""Полноценные тесты (quiz): learning_items.quiz_questions и quiz_attempts

Вопрос — {"text": str, "options": [{"text": str, "correct": bool}]}, тип
один (несколько правильных ответов, checkbox) — см. решение владельца
продукта 2026-09-23. quiz_questions живёт прямо на LearningItem, как steps
у snap_task — вопросы не переиспользуются между тестами (банк не нужен).

Revision ID: a2b3c4d5e6f7
Revises: f6a7b8c9d0e1
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa


revision = 'a2b3c4d5e6f7'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('learning_items', sa.Column('quiz_questions', sa.JSON(), nullable=True))

    op.create_table(
        'quiz_attempts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('item_id', sa.Integer(), sa.ForeignKey('learning_items.id'), nullable=False, index=True),
        # [[индексы выбранных вариантов по вопросу 0], [по вопросу 1], ...] —
        # порядок соответствует learning_items.quiz_questions на момент попытки.
        sa.Column('answers', sa.JSON(), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),  # 0..100, доля правильно отвеченных вопросов
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('quiz_attempts')
    op.drop_column('learning_items', 'quiz_questions')
