"""Задания ОГЭ с коротким числовым ответом."""
from alembic import op
import sqlalchemy as sa

revision = 'g7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None

def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE learningitemtype ADD VALUE IF NOT EXISTS 'OGE_TASK'")
    op.add_column('learning_items', sa.Column('oge_answer', sa.JSON(), nullable=True))
    op.create_table(
        'oge_attempts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('item_id', sa.Integer(), sa.ForeignKey('learning_items.id'), nullable=False, index=True),
        sa.Column('answer', sa.String(length=255), nullable=False),
        sa.Column('score', sa.Float(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

def downgrade() -> None:
    op.drop_table('oge_attempts')
    op.drop_column('learning_items', 'oge_answer')
