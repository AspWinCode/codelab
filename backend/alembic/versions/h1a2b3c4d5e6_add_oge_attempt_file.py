"""Необязательный файл к попытке ОГЭ — только в дополнение к автоответу."""
from alembic import op
import sqlalchemy as sa

revision = 'h1a2b3c4d5e6'
down_revision = 'g7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('oge_attempts', sa.Column('file_stored_name', sa.String(length=64), nullable=True))
    op.add_column('oge_attempts', sa.Column('file_original_filename', sa.String(length=255), nullable=True))
    op.add_column('oge_attempts', sa.Column('file_content_type', sa.String(length=128), nullable=True))
    op.add_column('oge_attempts', sa.Column('file_size', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('oge_attempts', 'file_size')
    op.drop_column('oge_attempts', 'file_content_type')
    op.drop_column('oge_attempts', 'file_original_filename')
    op.drop_column('oge_attempts', 'file_stored_name')
