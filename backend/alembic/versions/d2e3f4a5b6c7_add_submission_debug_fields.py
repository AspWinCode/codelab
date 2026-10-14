"""Add Submission.actual_output/expected_output/error_explanation — surfaces
the first failing test's actual-vs-expected output and a rule-based Russian
explanation of the error alongside the raw traceback (not replacing it).

Revision ID: d2e3f4a5b6c7
Revises: b1c2d3e4f5a6
"""
from alembic import op
import sqlalchemy as sa


revision = "d2e3f4a5b6c7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("submissions", sa.Column("actual_output", sa.Text(), nullable=True))
    op.add_column("submissions", sa.Column("expected_output", sa.Text(), nullable=True))
    op.add_column("submissions", sa.Column("error_explanation", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("submissions", "error_explanation")
    op.drop_column("submissions", "expected_output")
    op.drop_column("submissions", "actual_output")
