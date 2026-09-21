"""ADM-003: problem_revisions.sql_fixture (схема+seed для окружения sql-sqlite)

Revision ID: c3d4e5f6a7b8
Revises: b7c8d9e0f1a2
Create Date: 2026-09-21

"""
from alembic import op
import sqlalchemy as sa


revision = 'c3d4e5f6a7b8'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('problem_revisions', sa.Column('sql_fixture', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('problem_revisions', 'sql_fixture')
