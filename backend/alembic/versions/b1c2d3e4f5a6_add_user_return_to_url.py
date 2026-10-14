"""Store the LMS-signed "back to cabinet" destination on the user, so the
"Назад в кабинет" header button keeps working after the current Codelab
session has expired (the link itself needs no active auth).

Revision ID: b1c2d3e4f5a6
Revises: a8b9c0d1e2f3
"""
from alembic import op
import sqlalchemy as sa


revision = "b1c2d3e4f5a6"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("return_to_url", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "return_to_url")
