"""enriched_biometrics_and_idempotent_ingest

Revision ID: 0002_enriched_biometrics
Revises: 0001_initial_schema
Create Date: 2026-10-25 15:10:00.000000

Palier 3 - Ticket 2:
Tables: daily_metrics, workouts, sleep_sessions, sleep_stages, intraday_samples, hydration_logs, raw_ingest, user_consents.
Modifications colonnes:
- weights: external_id, measured_at, idempotency_key
- activities: external_id, idempotency_key
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002_enriched_biometrics'
down_revision: Union[str, Sequence[str], None] = '0001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Colonnes d'idempotence et multi-mesures sur weights
    with op.batch_alter_table('weights') as batch_op:
        batch_op.add_column(sa.Column('external_id', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('measured_at', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('idempotency_key', sa.Text(), nullable=True))

    # 2. Colonnes d'idempotence sur activities
    with op.batch_alter_table('activities') as batch_op:
        batch_op.add_column(sa.Column('external_id', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('idempotency_key', sa.Text(), nullable=True))

    # Index partiel/unique idempotence (source, external_id) si external_id non null
    op.create_index('idx_weights_source_external', 'weights', ['source', 'external_id'])
    op.create_index('idx_activities_source_external', 'activities', ['source', 'external_id'])

    # 3. daily_metrics
    op.create_table(
        'daily_metrics',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Text(), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('steps', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active_calories_kcal', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('total_calories_kcal', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('resting_hr_bpm', sa.Integer(), nullable=True),
        sa.Column('hrv_rmssd_ms', sa.Float(), nullable=True),
        sa.Column('hrv_sdnn_ms', sa.Float(), nullable=True),
        sa.Column('spo2_pct', sa.Float(), nullable=True),
        sa.Column('skin_temperature_c', sa.Float(), nullable=True),
        sa.Column('sleep_score', sa.Integer(), nullable=True),
        sa.Column('recovery_score', sa.Integer(), nullable=True),
        sa.Column('external_id', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.Text(), nullable=False),
        sa.UniqueConstraint('user_id', 'date', 'source', name='uq_daily_metrics_user_date_source'),
    )
    op.create_index('idx_daily_metrics_user_date', 'daily_metrics', ['user_id', 'date'])
    op.create_index('idx_daily_metrics_source_ext', 'daily_metrics', ['source', 'external_id'])

    # 4. workouts
    op.create_table(
        'workouts',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('external_id', sa.Text(), nullable=True),
        sa.Column('workout_type', sa.Text(), nullable=False),
        sa.Column('start_time', sa.Text(), nullable=False),
        sa.Column('end_time', sa.Text(), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('calories_kcal', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('avg_hr_bpm', sa.Integer(), nullable=True),
        sa.Column('max_hr_bpm', sa.Integer(), nullable=True),
        sa.Column('distance_meters', sa.Float(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.Text(), nullable=False),
    )
    op.create_index('idx_workouts_user_time', 'workouts', ['user_id', 'start_time'])
    op.create_index('idx_workouts_source_ext', 'workouts', ['source', 'external_id'])

    # 5. sleep_sessions
    op.create_table(
        'sleep_sessions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('external_id', sa.Text(), nullable=True),
        sa.Column('date', sa.Text(), nullable=False),
        sa.Column('start_time', sa.Text(), nullable=False),
        sa.Column('end_time', sa.Text(), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('efficiency_pct', sa.Float(), nullable=True),
        sa.Column('sleep_debt_minutes', sa.Integer(), nullable=True),
        sa.Column('sleep_score', sa.Integer(), nullable=True),
        sa.Column('deep_minutes', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('light_minutes', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('rem_minutes', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('awake_minutes', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.Text(), nullable=False),
    )
    op.create_index('idx_sleep_sessions_user_date', 'sleep_sessions', ['user_id', 'date'])
    op.create_index('idx_sleep_sessions_source_ext', 'sleep_sessions', ['source', 'external_id'])

    # 6. sleep_stages
    op.create_table(
        'sleep_stages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('sleep_session_id', sa.Integer(), sa.ForeignKey('sleep_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('stage', sa.Text(), nullable=False),  # 'awake', 'light', 'rem', 'deep'
        sa.Column('start_time', sa.Text(), nullable=False),
        sa.Column('end_time', sa.Text(), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), nullable=False),
    )
    op.create_index('idx_sleep_stages_session', 'sleep_stages', ['sleep_session_id'])

    # 7. intraday_samples
    op.create_table(
        'intraday_samples',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('metric_type', sa.Text(), nullable=False),  # 'hr', 'steps_hourly', 'spo2'
        sa.Column('timestamp', sa.Text(), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('unit', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False),
    )
    op.create_index('idx_intraday_samples_user_metric_time', 'intraday_samples', ['user_id', 'metric_type', 'timestamp'])

    # 8. hydration_logs
    op.create_table(
        'hydration_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Text(), nullable=False),
        sa.Column('timestamp', sa.Text(), nullable=False),
        sa.Column('volume_ml', sa.Float(), nullable=False),
        sa.Column('source', sa.Text(), nullable=False, server_default='manual'),
        sa.Column('external_id', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False),
    )
    op.create_index('idx_hydration_logs_user_date', 'hydration_logs', ['user_id', 'date'])

    # 9. raw_ingest
    op.create_table(
        'raw_ingest',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('endpoint', sa.Text(), nullable=True),
        sa.Column('idempotency_key', sa.Text(), nullable=True),
        sa.Column('payload_json', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False, server_default='received'),
        sa.Column('received_at', sa.Text(), nullable=False),
    )
    op.create_index('idx_raw_ingest_user_time', 'raw_ingest', ['user_id', 'received_at'])
    op.create_index('idx_raw_ingest_idempotency', 'raw_ingest', ['source', 'idempotency_key'])

    # 10. user_consents
    op.create_table(
        'user_consents',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('category', sa.Text(), nullable=False),  # 'biometrics', 'nutrition', 'analytics', 'devices'
        sa.Column('consented', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('updated_at', sa.Text(), nullable=False),
        sa.UniqueConstraint('user_id', 'category', name='uq_user_consents_user_cat'),
    )
    op.create_index('idx_user_consents_user', 'user_consents', ['user_id'])


def downgrade() -> None:
    op.drop_table('user_consents')
    op.drop_table('raw_ingest')
    op.drop_table('hydration_logs')
    op.drop_table('intraday_samples')
    op.drop_table('sleep_stages')
    op.drop_table('sleep_sessions')
    op.drop_table('workouts')
    op.drop_table('daily_metrics')

    with op.batch_alter_table('activities') as batch_op:
        batch_op.drop_index('idx_activities_source_external')
        batch_op.drop_column('idempotency_key')
        batch_op.drop_column('external_id')

    with op.batch_alter_table('weights') as batch_op:
        batch_op.drop_index('idx_weights_source_external')
        batch_op.drop_column('idempotency_key')
        batch_op.drop_column('measured_at')
        batch_op.drop_column('external_id')
