"""Проект с ручной проверкой: learningitemtype=PROJECT, learning_items.due_at,
project_submissions/project_files/project_file_comments, новые notificationtype

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-27

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE learningitemtype ADD VALUE IF NOT EXISTS 'PROJECT'")
        op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'PROJECT_REVIEWED'")
        op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'PROJECT_REMINDER'")

    op.add_column('learning_items', sa.Column('due_at', sa.DateTime(timezone=True), nullable=True))

    project_submission_status = sa.Enum(
        'DRAFT', 'SUBMITTED', 'NEEDS_REVISION', 'ACCEPTED',
        name='projectsubmissionstatus',
    )
    project_submission_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'project_submissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('learning_item_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('status', project_submission_status, nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('review_comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['learning_item_id'], ['learning_items.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_project_submissions_learning_item_id'), 'project_submissions', ['learning_item_id'], unique=False)
    op.create_index(op.f('ix_project_submissions_user_id'), 'project_submissions', ['user_id'], unique=False)

    op.create_table(
        'project_files',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('submission_id', sa.Integer(), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('stored_name', sa.String(length=64), nullable=False),
        sa.Column('content_type', sa.String(length=128), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['submission_id'], ['project_submissions.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_project_files_submission_id'), 'project_files', ['submission_id'], unique=False)

    op.create_table(
        'project_file_comments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('file_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['file_id'], ['project_files.id'], ),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_project_file_comments_file_id'), 'project_file_comments', ['file_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_project_file_comments_file_id'), table_name='project_file_comments')
    op.drop_table('project_file_comments')
    op.drop_index(op.f('ix_project_files_submission_id'), table_name='project_files')
    op.drop_table('project_files')
    op.drop_index(op.f('ix_project_submissions_user_id'), table_name='project_submissions')
    op.drop_index(op.f('ix_project_submissions_learning_item_id'), table_name='project_submissions')
    op.drop_table('project_submissions')
    sa.Enum(name='projectsubmissionstatus').drop(op.get_bind(), checkfirst=True)
    op.drop_column('learning_items', 'due_at')
