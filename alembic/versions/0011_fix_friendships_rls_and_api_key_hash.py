"""Fix friendships RLS policy (include friend_user_id) and backfill api_key_hash from api_key.

Revision ID: 0011_fix_friendships_rls_and_api_key_hash
Revises: 0010_add_refresh_tokens_table
Create Date: 2026-11-27 22:02:00.000000
"""

import hashlib
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0011_fix_friendships_rls_and_api_key_hash"
down_revision = "0010_add_refresh_tokens_table"
branch_labels = None
depends_on = None


def _extract_token(enc_cred: str | None, api_key: str | None) -> str | None:
    if enc_cred:
        try:
            from src.crypto import decrypt_credentials

            creds = decrypt_credentials(enc_cred) or {}
            for key in ("api_key", "webhook_secret", "token", "bearer_token", "webhook_token"):
                val = creds.get(key)
                if val and str(val).strip():
                    return str(val).strip()
        except Exception:
            pass

    if api_key and str(api_key).strip():
        raw = str(api_key).strip()
        if raw.startswith("enc::"):
            try:
                from src.crypto import decrypt_data

                dec = decrypt_data(raw)
                if dec and str(dec).strip():
                    return str(dec).strip()
            except Exception:
                return None
        return raw

    return None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS rls_friendships_user_isolation ON friendships;")
        op.execute(
            """
            CREATE POLICY rls_friendships_user_isolation ON friendships
            FOR ALL
            USING (
                NULLIF(current_setting('app.current_user_id', true), '') IS NULL
                OR user_id = NULLIF(current_setting('app.current_user_id', true), '')::integer
                OR friend_user_id = NULLIF(current_setting('app.current_user_id', true), '')::integer
            )
            WITH CHECK (
                NULLIF(current_setting('app.current_user_id', true), '') IS NULL
                OR user_id = NULLIF(current_setting('app.current_user_id', true), '')::integer
                OR friend_user_id = NULLIF(current_setting('app.current_user_id', true), '')::integer
            );
            """
        )

    if op.get_context().as_sql:
        return

    rows = conn.execute(
        sa.text(
            "SELECT user_id, device_id, encrypted_credentials, api_key "
            "FROM user_devices "
            "WHERE api_key_hash IS NULL "
            "AND (encrypted_credentials IS NOT NULL OR api_key IS NOT NULL)"
        )
    ).fetchall()

    for user_id, device_id, enc_cred, api_key in rows:
        token = _extract_token(enc_cred, api_key)
        if not token:
            continue
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        conn.execute(
            sa.text(
                "UPDATE user_devices SET api_key_hash = :h "
                "WHERE user_id = :uid AND device_id = :did"
            ),
            {"h": token_hash, "uid": user_id, "did": device_id},
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS rls_friendships_user_isolation ON friendships;")
        op.execute(
            """
            CREATE POLICY rls_friendships_user_isolation ON friendships
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
