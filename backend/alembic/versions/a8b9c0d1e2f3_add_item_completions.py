"""Store completion state for non-gradable course materials.

Revision ID: a8b9c0d1e2f3
Revises: f6a7b8c9d0e1
"""
from alembic import op
import sqlalchemy as sa


revision = "a8b9c0d1e2f3"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "item_completions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("learning_items.id"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "item_id", name="uq_user_item_completion"),
    )
    op.create_index("ix_item_completions_user_id", "item_completions", ["user_id"])
    op.create_index("ix_item_completions_item_id", "item_completions", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_item_completions_item_id", table_name="item_completions")
    op.drop_index("ix_item_completions_user_id", table_name="item_completions")
    op.drop_table("item_completions")
