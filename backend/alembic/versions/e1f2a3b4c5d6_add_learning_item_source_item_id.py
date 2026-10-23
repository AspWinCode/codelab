"""Отслеживание происхождения learning_items.id между версиями курса.

Публикация клонирует все айтемы в новый CourseVersion с НОВЫМИ id (см.
publish_course), чтобы правки черновика не задевали уже назначенное
ученикам. ProjectSubmission/ItemCompletion/Enrollment.last_item_id жёстко
ссылаются на конкретный learning_item_id — без source_item_id после второй
публикации подряд эти ссылки указывают на уже неактивную версию и
"пропадают" для преподавателя/ученика. source_item_id хранит id айтема, из
которого был сделан клон (внутри ТОЙ ЖЕ публикации), и позволяет
publish_course переносить такие ссылки на новый активный айтем.

Revision ID: e1f2a3b4c5d6
Revises: d8e9f0a1b2c3
Create Date: 2026-10-23

"""
import sqlalchemy as sa
from alembic import op


revision = 'e1f2a3b4c5d6'
down_revision = 'd8e9f0a1b2c3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('learning_items', sa.Column('source_item_id', sa.Integer(), nullable=True))
    op.create_index('ix_learning_items_source_item_id', 'learning_items', ['source_item_id'])
    op.create_foreign_key(
        'fk_learning_items_source_item_id', 'learning_items', 'learning_items',
        ['source_item_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_learning_items_source_item_id', 'learning_items', type_='foreignkey')
    op.drop_index('ix_learning_items_source_item_id', table_name='learning_items')
    op.drop_column('learning_items', 'source_item_id')
