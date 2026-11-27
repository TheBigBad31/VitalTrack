"""add_refresh_tokens_table

Revision ID: 0010_add_refresh_tokens_table
Revises: 0010_backfill_user_devices_api_key_hash
Create Date: 2026-11-27 09:25:00.000000

BALI-315 : Ajoute la table refresh_tokens pour les refresh tokens révocables
hashés en SHA-256 avec rotation et détection de réutilisation par famille.
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0010_add_refresh_tokens_table'
down_revision: Union[str, Sequence[str], None] = '0010_backfill_user_devices_api_key_hash'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_refresh_tokens_table() -> None:
    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.Text(), nullable=False, unique=True),
        sa.Column('family_id', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.Text(), nullable=False),
        sa.Column('revoked_at', sa.Text(), nullable=True),
        sa.Column('replaced_by_hash', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('user_agent', sa.Text(), nullable=True),
    )
    op.create_index('idx_refresh_tokens_user_id', 'refresh_tokens', ['user_id'])
    op.create_index('idx_refresh_tokens_family_id', 'refresh_tokens', ['family_id'])
    op.create_index('idx_refresh_tokens_token_hash', 'refresh_tokens', ['token_hash'], unique=True)


def upgrade() -> None:
    if context.is_offline_mode():
        _create_refresh_tokens_table()
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'refresh_tokens' not in existing_tables:
        _create_refresh_tokens_table()

    if bind.dialect.name == 'postgresql':
        policy_name = 'rls_refresh_tokens_user_isolation'
        op.execute("ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE refresh_tokens FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS {policy_name} ON refresh_tokens;")
        op.execute(
            f"""
            CREATE POLICY {policy_name} ON refresh_tokens
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


def downgrade() -> None:
    if context.is_offline_mode():
        op.drop_index('idx_refresh_tokens_token_hash', table_name='refresh_tokens')
        op.drop_index('idx_refresh_tokens_family_id', table_name='refresh_tokens')
        op.drop_index('idx_refresh_tokens_user_id', table_name='refresh_tokens')
        op.drop_table('refresh_tokens')
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'refresh_tokens' in existing_tables:
        if bind.dialect.name == 'postgresql':
            op.execute("DROP POLICY IF EXISTS rls_refresh_tokens_user_isolation ON refresh_tokens;")
            op.execute("ALTER TABLE refresh_tokens NO FORCE ROW LEVEL SECURITY;")
            op.execute("ALTER TABLE refresh_tokens DISABLE ROW LEVEL SECURITY;")
        op.drop_index('idx_refresh_tokens_token_hash', table_name='refresh_tokens')
        op.drop_index('idx_refresh_tokens_family_id', table_name='refresh_tokens')
        op.drop_index('idx_refresh_tokens_user_id', table_name='refresh_tokens')
        op.drop_table('refresh_tokens')
