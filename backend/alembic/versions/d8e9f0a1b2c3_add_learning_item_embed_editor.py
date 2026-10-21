"""Проект со встроенным редактором (пока только 'turtle'): learning_items.embed_editor.

type=project по-прежнему идёт по всему циклу ProjectSubmission (ручная
проверка тренером) — embed_editor только подсказывает фронтенду, что справа
нужно показать iframe редактора (как у turtle_task), а не форму ручной
загрузки файла, см. app/routers/projects.py и frontend CoursePage.tsx.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-10-21

"""
import sqlalchemy as sa
from alembic import op


revision = 'd8e9f0a1b2c3'
down_revision = 'c7d8e9f0a1b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('learning_items', sa.Column('embed_editor', sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column('learning_items', 'embed_editor')
