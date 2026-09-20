"""add enrollment last_item_id

Revision ID: 2da621bab1df
Revises: 4ac63acc21f5
Create Date: 2026-09-21 00:59:54.630504

"""
from alembic import op
import sqlalchemy as sa


revision = '2da621bab1df'
down_revision = '4ac63acc21f5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('enrollments', sa.Column('last_item_id', sa.Integer(), nullable=True))
    # Именуем явно: autogenerate оставляет create_foreign_key(None, ...), а
    # безымянный constraint потом нечем адресовать в downgrade() — на Postgres
    # это упало бы при откате миграции.
    op.create_foreign_key(
        'fk_enrollments_last_item_id', 'enrollments', 'learning_items', ['last_item_id'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_enrollments_last_item_id', 'enrollments', type_='foreignkey')
    op.drop_column('enrollments', 'last_item_id')
