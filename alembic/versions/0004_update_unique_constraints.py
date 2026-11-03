"""update_unique_constraints_weights_activities_add_timezone

Revision ID: 0004_update_unique_constraints
Revises: e51b5ce69a60
Create Date: 2026-11-03 00:00:00.000000

Migration pour:
1. Changer la contrainte unique de weights de (user_id, date) à (user_id, date, source)
2. Changer la contrainte unique de activities de (user_id, date) à (user_id, date, source)
3. Ajouter colonne timezone à user_profile
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004_update_unique_constraints'
down_revision: Union[str, Sequence[str], None] = 'b5e439c530ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Ajouter colonne timezone à user_profile
    op.add_column('user_profile', sa.Column('timezone', sa.Text(), nullable=False, server_default='UTC'))
    
    # 2. Mettre à jour weights : supprimer l'ancienne contrainte unique et créer la nouvelle
    # SQLite ne supporte pas DROP CONSTRAINT directement, il faut recréer la table
    # Pour PostgreSQL, on peut utiliser ALTER TABLE
    from alembic import context
    if context.get_context().dialect.name == 'postgresql':
        # PostgreSQL: drop et recréer les contraintes
        op.drop_constraint('uq_weights_user_date', 'weights', type_='unique')
        op.create_unique_constraint('uq_weights_user_date_source', 'weights', ['user_id', 'date', 'source'])
        
        op.drop_constraint('uq_activities_user_date', 'activities', type_='unique')
        op.create_unique_constraint('uq_activities_user_date_source', 'activities', ['user_id', 'date', 'source'])
    else:
        # SQLite: recréer les tables (approche plus sûre)
        # weights
        op.execute("""
            CREATE TABLE weights_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                date TEXT NOT NULL,
                weight_kg REAL NOT NULL,
                body_fat_pct REAL,
                muscle_mass_kg REAL,
                water_pct REAL,
                bmi REAL,
                trend_7d_kg REAL,
                source TEXT NOT NULL,
                notes TEXT,
                external_id TEXT,
                measured_at TEXT,
                idempotency_key TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, date, source)
            )
        """)
        op.execute("INSERT INTO weights_new SELECT * FROM weights")
        op.drop_table('weights')
        op.rename_table('weights_new', 'weights')
        op.create_index('idx_weights_user_date', 'weights', ['user_id', 'date'])
        
        # activities
        op.execute("""
            CREATE TABLE activities_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                date TEXT NOT NULL,
                steps INTEGER NOT NULL,
                active_calories_kcal REAL NOT NULL,
                bmr_kcal REAL NOT NULL,
                total_burned_kcal REAL NOT NULL,
                workout_minutes INTEGER NOT NULL,
                workout_type TEXT,
                resting_hr_bpm INTEGER,
                hrv_ms REAL,
                sleep_score INTEGER,
                source TEXT NOT NULL,
                external_id TEXT,
                idempotency_key TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, date, source)
            )
        """)
        op.execute("INSERT INTO activities_new SELECT * FROM activities")
        op.drop_table('activities')
        op.rename_table('activities_new', 'activities')
        op.create_index('idx_activities_user_date', 'activities', ['user_id', 'date'])


def downgrade() -> None:
    # Supprimer colonne timezone
    op.drop_column('user_profile', 'timezone')
    
    from alembic import context
    if context.get_context().dialect.name == 'postgresql':
        op.drop_constraint('uq_weights_user_date_source', 'weights', type_='unique')
        op.create_unique_constraint('uq_weights_user_date', 'weights', ['user_id', 'date'])
        
        op.drop_constraint('uq_activities_user_date_source', 'activities', type_='unique')
        op.create_unique_constraint('uq_activities_user_date', 'activities', ['user_id', 'date'])
    else:
        # SQLite: recréer les tables avec l'ancienne contrainte
        op.execute("""
            CREATE TABLE weights_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                date TEXT NOT NULL,
                weight_kg REAL NOT NULL,
                body_fat_pct REAL,
                muscle_mass_kg REAL,
                water_pct REAL,
                bmi REAL,
                trend_7d_kg REAL,
                source TEXT NOT NULL,
                notes TEXT,
                external_id TEXT,
                measured_at TEXT,
                idempotency_key TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, date)
            )
        """)
        op.execute("INSERT INTO weights_new SELECT * FROM weights")
        op.drop_table('weights')
        op.rename_table('weights_new', 'weights')
        op.create_index('idx_weights_user_date', 'weights', ['user_id', 'date'])
        # Recréer les index attendus par la migration 0002 downgrade
        op.create_index('idx_weights_source_external', 'weights', ['source', 'external_id'])
        
        op.execute("""
            CREATE TABLE activities_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                date TEXT NOT NULL,
                steps INTEGER NOT NULL,
                active_calories_kcal REAL NOT NULL,
                bmr_kcal REAL NOT NULL,
                total_burned_kcal REAL NOT NULL,
                workout_minutes INTEGER NOT NULL,
                workout_type TEXT,
                resting_hr_bpm INTEGER,
                hrv_ms REAL,
                sleep_score INTEGER,
                source TEXT NOT NULL,
                external_id TEXT,
                idempotency_key TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, date)
            )
        """)
        op.execute("INSERT INTO activities_new SELECT * FROM activities")
        op.drop_table('activities')
        op.rename_table('activities_new', 'activities')
        op.create_index('idx_activities_user_date', 'activities', ['user_id', 'date'])
        # Recréer les index attendus par la migration 0002 downgrade
        op.create_index('idx_activities_source_external', 'activities', ['source', 'external_id'])