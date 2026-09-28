"""add 3x job hunt: hunt_configs, hunt_results, jobs.source_updated_at

Revision ID: b4d8e2f1a9c3
Revises: 77caf9f20440
Create Date: 2026-09-27 10:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

import app.db.base


revision = 'b4d8e2f1a9c3'
down_revision = '77caf9f20440'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_updated_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table('hunt_configs',
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('experience_years', sa.Float(), nullable=True),
    sa.Column('target_roles', app.db.base.JSONColumn(), nullable=False),
    sa.Column('skills', app.db.base.JSONColumn(), nullable=False),
    sa.Column('role_keywords', app.db.base.JSONColumn(), nullable=False),
    sa.Column('excluded_seniority', app.db.base.JSONColumn(), nullable=False),
    sa.Column('location_tiers', app.db.base.JSONColumn(), nullable=False),
    sa.Column('country', sa.String(length=80), nullable=False),
    sa.Column('country_places', app.db.base.JSONColumn(), nullable=False),
    sa.Column('accept_worldwide_remote', sa.Boolean(), nullable=False),
    sa.Column('auto_queries', sa.Boolean(), nullable=False),
    sa.Column('custom_queries', app.db.base.JSONColumn(), nullable=False),
    sa.Column('excluded_queries', app.db.base.JSONColumn(), nullable=False),
    sa.Column('max_queries', sa.Integer(), nullable=False),
    sa.Column('results_per_query', sa.Integer(), nullable=False),
    sa.Column('max_age_days', sa.Integer(), nullable=False),
    sa.Column('apply_first_threshold', sa.Integer(), nullable=False),
    sa.Column('min_skill_overlap', sa.Float(), nullable=False),
    sa.Column('weights', app.db.base.JSONColumn(), nullable=False),
    sa.Column('semantic_mode', sa.String(length=20), nullable=False),
    sa.Column('respect_policy_filters', sa.Boolean(), nullable=False),
    sa.Column('notify_new_matches', sa.Boolean(), nullable=False),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_run_summary', app.db.base.JSONColumn(), nullable=False),
    sa.Column('last_assessed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('hunt_configs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_hunt_configs_user_id'), ['user_id'], unique=True)

    op.create_table('hunt_results',
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('job_id', sa.String(length=32), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('section', sa.String(length=160), nullable=False),
    sa.Column('tier_name', sa.String(length=120), nullable=False),
    sa.Column('tier_rank', sa.Integer(), nullable=True),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('strength', sa.String(length=20), nullable=False),
    sa.Column('work_mode', sa.String(length=20), nullable=False),
    sa.Column('remote_region', sa.String(length=40), nullable=False),
    sa.Column('seniority', sa.String(length=20), nullable=False),
    sa.Column('experience_fit', sa.String(length=20), nullable=False),
    sa.Column('skill_overlap', sa.Float(), nullable=True),
    sa.Column('matched_skills', app.db.base.JSONColumn(), nullable=False),
    sa.Column('missing_skills', app.db.base.JSONColumn(), nullable=False),
    sa.Column('semantic_score', sa.Float(), nullable=True),
    sa.Column('freshness_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('freshness_basis', sa.String(length=20), nullable=False),
    sa.Column('apply_link_type', sa.String(length=20), nullable=False),
    sa.Column('apply_link_label', sa.String(length=80), nullable=False),
    sa.Column('best_apply_url', sa.String(length=1000), nullable=False),
    sa.Column('public_contact_email', sa.String(length=320), nullable=False),
    sa.Column('reasons', app.db.base.JSONColumn(), nullable=False),
    sa.Column('highlights', app.db.base.JSONColumn(), nullable=False),
    sa.Column('warnings', app.db.base.JSONColumn(), nullable=False),
    sa.Column('breakdown', app.db.base.JSONColumn(), nullable=False),
    sa.Column('explanation', sa.Text(), nullable=False),
    sa.Column('assessed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'job_id', name='uq_hunt_result_job')
    )
    with op.batch_alter_table('hunt_results', schema=None) as batch_op:
        batch_op.create_index('ix_hunt_results_user_category', ['user_id', 'category'], unique=False)
        batch_op.create_index(batch_op.f('ix_hunt_results_job_id'), ['job_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hunt_results_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('hunt_results', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_hunt_results_user_id'))
        batch_op.drop_index(batch_op.f('ix_hunt_results_job_id'))
        batch_op.drop_index('ix_hunt_results_user_category')
    op.drop_table('hunt_results')

    with op.batch_alter_table('hunt_configs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_hunt_configs_user_id'))
    op.drop_table('hunt_configs')

    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_column('source_updated_at')
