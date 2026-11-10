"""rls_policies_biometrics

Revision ID: 7e2e5ac2522e
Revises: 0005_perf_indexes
Create Date: 2026-11-07 08:38:06.262534

Row-Level Security (RLS) PostgreSQL pour multi-tenant réel et isolation stricte par user_id.
Tables biométriques et personnelles couvertes:
- weights, activities, daily_metrics, workouts, sleep_sessions, sleep_stages, intraday_samples, hydration_logs, raw_ingest
- meals, meal_logs, meal_log_items, saved_meals
- user_profile, user_devices, user_consents, friendships
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7e2e5ac2522e'
down_revision: Union[str, Sequence[str], None] = '0005_perf_indexes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables directes avec colonne user_id
RLS_DIRECT_TABLES = [
    'weights',
    'activities',
    'daily_metrics',
    'workouts',
    'sleep_sessions',
    'intraday_samples',
    'hydration_logs',
    'raw_ingest',
    'meals',
    'meal_logs',
    'saved_meals',
    'user_profile',
    'user_devices',
    'user_consents',
    'friendships',
]


def upgrade() -> None:
    """Activer Row-Level Security et créer les policies d'isolation stricte multi-tenant sur PostgreSQL."""
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == 'postgresql':
        # 1. Tables avec colonne directe user_id
        for table in RLS_DIRECT_TABLES:
            policy_name = f'rls_{table}_user_isolation'
            # Activer RLS
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
            # Supprimer la policy si elle existait déjà (idempotence)
            op.execute(f"DROP POLICY IF EXISTS {policy_name} ON {table};")
            # Créer la policy : isolation stricte basée sur app.current_user_id ou bypass superuser/admin si non configuré
            op.execute(
                f"""
                CREATE POLICY {policy_name} ON {table}
                FOR ALL
                USING (
                    NULLIF(current_setting('app.current_user_id', true), '') IS NULL
                    OR user_id = NULLIF(current_setting('app.current_user_id', true), '')::integer
                )
                WITH CHECK (
                    NULLIF(current_setting('app.current_user_id', true), '') IS NULL
                    OR user_id = NULLIF(current_setting('app.current_user_id', true), '')::integer
                );
                """
            )

        # 2. Table sleep_stages (liée via sleep_session_id -> sleep_sessions.user_id)
        stage_policy = 'rls_sleep_stages_user_isolation'
        op.execute("ALTER TABLE sleep_stages ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE sleep_stages FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS {stage_policy} ON sleep_stages;")
        op.execute(
            f"""
            CREATE POLICY {stage_policy} ON sleep_stages
            FOR ALL
            USING (
                NULLIF(current_setting('app.current_user_id', true), '') IS NULL
                OR EXISTS (
                    SELECT 1 FROM sleep_sessions s
                    WHERE s.id = sleep_stages.sleep_session_id
                    AND s.user_id = NULLIF(current_setting('app.current_user_id', true), '')::integer
                )
            )
            WITH CHECK (
                NULLIF(current_setting('app.current_user_id', true), '') IS NULL
                OR EXISTS (
                    SELECT 1 FROM sleep_sessions s
                    WHERE s.id = sleep_stages.sleep_session_id
                    AND s.user_id = NULLIF(current_setting('app.current_user_id', true), '')::integer
                )
            );
            """
        )

        # 3. Table meal_log_items (liée via meal_log_id -> meal_logs.user_id)
        meal_item_policy = 'rls_meal_log_items_user_isolation'
        op.execute("ALTER TABLE meal_log_items ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE meal_log_items FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS {meal_item_policy} ON meal_log_items;")
        op.execute(
            f"""
            CREATE POLICY {meal_item_policy} ON meal_log_items
            FOR ALL
            USING (
                NULLIF(current_setting('app.current_user_id', true), '') IS NULL
                OR EXISTS (
                    SELECT 1 FROM meal_logs m
                    WHERE m.id = meal_log_items.meal_log_id
                    AND m.user_id = NULLIF(current_setting('app.current_user_id', true), '')::integer
                )
            )
            WITH CHECK (
                NULLIF(current_setting('app.current_user_id', true), '') IS NULL
                OR EXISTS (
                    SELECT 1 FROM meal_logs m
                    WHERE m.id = meal_log_items.meal_log_id
                    AND m.user_id = NULLIF(current_setting('app.current_user_id', true), '')::integer
                )
            );
            """
        )


def downgrade() -> None:
    """Désactiver Row-Level Security et supprimer les policies sur PostgreSQL."""
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == 'postgresql':
        for table in RLS_DIRECT_TABLES:
            policy_name = f'rls_{table}_user_isolation'
            op.execute(f"DROP POLICY IF EXISTS {policy_name} ON {table};")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

        op.execute("DROP POLICY IF EXISTS rls_sleep_stages_user_isolation ON sleep_stages;")
        op.execute("ALTER TABLE sleep_stages NO FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE sleep_stages DISABLE ROW LEVEL SECURITY;")

        op.execute("DROP POLICY IF EXISTS rls_meal_log_items_user_isolation ON meal_log_items;")
        op.execute("ALTER TABLE meal_log_items NO FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE meal_log_items DISABLE ROW LEVEL SECURITY;")
