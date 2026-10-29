"""public_catalog_and_subscriptions

Revision ID: 0003_public_catalog_and_subscriptions
Revises: 0002_enriched_biometrics
Create Date: 2026-10-28 08:30:00.000000

Issue BALI-83:
1. Ajout de is_public sur la table food_items (défaut FALSE / 0).
2. Création de la table catalog_subscriptions (subscriber_id, target_user_id, created_at).
3. Création des index associés.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003_public_catalog_and_subscriptions'
down_revision: Union[str, Sequence[str], None] = '0002_enriched_biometrics'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Colonne is_public sur food_items
    with op.batch_alter_table('food_items') as batch_op:
        batch_op.add_column(sa.Column('is_public', sa.Boolean(), server_default=sa.text('false' if op.get_bind().dialect.name == 'postgresql' else '0'), nullable=True))

    op.create_index('idx_food_items_public', 'food_items', ['is_public'])

    # 2. Table catalog_subscriptions
    op.create_table(
        'catalog_subscriptions',
        sa.Column('subscriber_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True, nullable=False),
        sa.Column('target_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True, nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False),
    )

    op.create_index('idx_catalog_subscriptions_sub', 'catalog_subscriptions', ['subscriber_id'])
    op.create_index('idx_catalog_subscriptions_target', 'catalog_subscriptions', ['target_user_id'])


def downgrade() -> None:
    op.drop_index('idx_catalog_subscriptions_target', table_name='catalog_subscriptions')
    op.drop_index('idx_catalog_subscriptions_sub', table_name='catalog_subscriptions')
    op.drop_table('catalog_subscriptions')

    op.drop_index('idx_food_items_public', table_name='food_items')
    with op.batch_alter_table('food_items') as batch_op:
        batch_op.drop_column('is_public')
