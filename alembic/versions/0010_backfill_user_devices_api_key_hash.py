"""Backfill api_key_hash on user_devices for fast O(1) webhook token lookup.

Revision ID: 0010_backfill_user_devices_api_key_hash
Revises: 0009_add_user_profile_nutrition_goals_config
Create Date: 2026-11-27 09:23:00.000000
"""

import hashlib
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0010_backfill_user_devices_api_key_hash"
down_revision = "0009_add_user_profile_nutrition_goals_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().as_sql:
        return
    conn = op.get_bind()
    try:
        from src.crypto import decrypt_credentials
    except Exception:
        return

    rows = conn.execute(
        sa.text(
            "SELECT user_id, device_id, encrypted_credentials "
            "FROM user_devices "
            "WHERE api_key_hash IS NULL AND encrypted_credentials IS NOT NULL"
        )
    ).fetchall()

    for row in rows:
        user_id, device_id, enc = row[0], row[1], row[2]
        try:
            creds = decrypt_credentials(enc) or {}
        except Exception:
            continue
        for key in ("api_key", "webhook_secret", "token", "bearer_token", "webhook_token"):
            val = creds.get(key)
            if val and str(val).strip():
                token_hash = hashlib.sha256(str(val).strip().encode("utf-8")).hexdigest()
                conn.execute(
                    sa.text(
                        "UPDATE user_devices SET api_key_hash = :h "
                        "WHERE user_id = :uid AND device_id = :did"
                    ),
                    {"h": token_hash, "uid": user_id, "did": device_id},
                )
                break


def downgrade() -> None:
    pass
