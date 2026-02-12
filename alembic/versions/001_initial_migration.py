"""Initial migration - create all tables

Revision ID: 001
Revises: 
Create Date: 2026-02-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create subjects table
    op.create_table(
        'subjects',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'name', name='uq_user_subject_name')
    )
    op.create_index('ix_subjects_user_name', 'subjects', ['user_id', 'name'])

    # Create weekly_allocations table
    op.create_table(
        'weekly_allocations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('subject_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('week_start_date', sa.Date(), nullable=False),
        sa.Column('minutes_allocated', sa.Integer(), nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint('minutes_allocated >= 0', name='ck_minutes_allocated_positive'),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'subject_id', 'week_start_date', name='uq_user_subject_week')
    )
    op.create_index('ix_allocations_user_week', 'weekly_allocations', ['user_id', 'week_start_date'])
    op.create_index('ix_allocations_subject_week', 'weekly_allocations', ['subject_id', 'week_start_date'])

    # Create sessions table
    op.create_table(
        'sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subject_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('started_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('ended_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('goal', sa.Text(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('total_paused_seconds', sa.Integer(), nullable=False),
        sa.Column('pause_started_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('effective_override_seconds', sa.Integer(), nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint('total_paused_seconds >= 0', name='ck_total_paused_seconds_positive'),
        sa.CheckConstraint(
            'effective_override_seconds IS NULL OR effective_override_seconds >= 0',
            name='ck_effective_override_seconds_positive'
        ),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_sessions_user_status', 'sessions', ['user_id', 'status'])
    op.create_index('ix_sessions_user_started', 'sessions', ['user_id', 'started_at'])


def downgrade() -> None:
    op.drop_index('ix_sessions_user_started', table_name='sessions')
    op.drop_index('ix_sessions_user_status', table_name='sessions')
    op.drop_table('sessions')
    
    op.drop_index('ix_allocations_subject_week', table_name='weekly_allocations')
    op.drop_index('ix_allocations_user_week', table_name='weekly_allocations')
    op.drop_table('weekly_allocations')
    
    op.drop_index('ix_subjects_user_name', table_name='subjects')
    op.drop_table('subjects')
    
    op.drop_table('users')
