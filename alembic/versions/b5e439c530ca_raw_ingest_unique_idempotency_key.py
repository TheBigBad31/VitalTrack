"""raw_ingest_unique_idempotency_key

Revision ID: b5e439c530ca
Revises: e51b5ce69a60
Create Date: 2026-11-03 08:45:11.228696

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5e439c530ca'
down_revision: Union[str, Sequence[str], None] = 'e51b5ce69a60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add api_key_hash column to user_devices and unique index on raw_ingest(idempotency_key)."""
    # 1. user_devices.api_key_hash
    with op.batch_alter_table('user_devices') as batch_op:
        batch_op.add_column(sa.Column('api_key_hash', sa.Text(), nullable=True))
        batch_op.create_index('idx_user_devices_api_key_hash', ['api_key_hash'], unique=False)

    # 2. raw_ingest.idempotency_key unique constraint/index
    op.create_index(
        'uq_raw_ingest_idempotency_key',
        'raw_ingest',
        ['idempotency_key'],
        unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_raw_ingest_idempotency_key', table_name='raw_ingest')
    with op.batch_alter_table('user_devices') as batch_op:
        batch_op.drop_index('idx_user_devices_api_key_hash')
        batch_op.drop_column('api_key_hash')
