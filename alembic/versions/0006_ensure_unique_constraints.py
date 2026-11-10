"""ensure_unique_constraints_weights_activities

Revision ID: 0006_ensure_unique_constraints
Revises: 7e2e5ac2522e
Create Date: 2026-11-10 13:12:00.000000

Garantit la présence des contraintes uniques composites (user_id, date, source)
sur les tables PostgreSQL Neon `weights` et `activities` pour satisfaire les clauses
`ON CONFLICT(user_id, date, source) DO UPDATE`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006_ensure_unique_constraints'
down_revision: Union[str, Sequence[str], None] = '7e2e5ac2522e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == 'postgresql':
        # 1. Contraintes uniques sur weights
        op.execute("""
            DO $$
            BEGIN
                -- Supprimer l'ancienne contrainte (user_id, date) si présente
                IF EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_weights_user_date'
                ) THEN
                    ALTER TABLE weights DROP CONSTRAINT uq_weights_user_date;
                END IF;

                -- Créer la contrainte composite (user_id, date, source) si absente
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_weights_user_date_source'
                ) THEN
                    ALTER TABLE weights ADD CONSTRAINT uq_weights_user_date_source UNIQUE (user_id, date, source);
                END IF;
            END $$;
        """)

        # 2. Contraintes uniques sur activities
        op.execute("""
            DO $$
            BEGIN
                -- Supprimer l'ancienne contrainte (user_id, date) si présente
                IF EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_activities_user_date'
                ) THEN
                    ALTER TABLE activities DROP CONSTRAINT uq_activities_user_date;
                END IF;

                -- Créer la contrainte composite (user_id, date, source) si absente
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_activities_user_date_source'
                ) THEN
                    ALTER TABLE activities ADD CONSTRAINT uq_activities_user_date_source UNIQUE (user_id, date, source);
                END IF;
            END $$;
        """)
    else:
        # SQLite gère déjà UNIQUE(user_id, date, source) dans 0004
        pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == 'postgresql':
        op.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_weights_user_date_source'
                ) THEN
                    ALTER TABLE weights DROP CONSTRAINT uq_weights_user_date_source;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_weights_user_date'
                ) THEN
                    ALTER TABLE weights ADD CONSTRAINT uq_weights_user_date UNIQUE (user_id, date);
                END IF;

                IF EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_activities_user_date_source'
                ) THEN
                    ALTER TABLE activities DROP CONSTRAINT uq_activities_user_date_source;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_activities_user_date'
                ) THEN
                    ALTER TABLE activities ADD CONSTRAINT uq_activities_user_date UNIQUE (user_id, date);
                END IF;
            END $$;
        """)
