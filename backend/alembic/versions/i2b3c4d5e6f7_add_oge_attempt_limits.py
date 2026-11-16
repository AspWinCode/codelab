"""Лимит попыток ОГЭ и настройки показа результата/правильного ответа (Этап 3)."""
from alembic import op
import sqlalchemy as sa

revision = 'i2b3c4d5e6f7'
down_revision = 'h1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('learning_items', sa.Column('oge_max_attempts', sa.Integer(), nullable=True))
    op.add_column(
        'learning_items',
        sa.Column('oge_allow_retry_after_success', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        'learning_items',
        sa.Column('oge_show_result_immediately', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        'learning_items',
        sa.Column('oge_show_correct_answer', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('learning_items', 'oge_show_correct_answer')
    op.drop_column('learning_items', 'oge_show_result_immediately')
    op.drop_column('learning_items', 'oge_allow_retry_after_success')
    op.drop_column('learning_items', 'oge_max_attempts')
