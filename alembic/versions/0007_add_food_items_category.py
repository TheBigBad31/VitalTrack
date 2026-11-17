"""add_food_items_category

Revision ID: 0007_add_food_items_category
Revises: 0006_ensure_unique_constraints
Create Date: 2026-11-17 14:50:00.000000

BALI-273 : Ajoute la colonne `category` sur `food_items` pour classer,
filtrer et trier les aliments et plats du catalogue.
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007_add_food_items_category'
down_revision: Union[str, Sequence[str], None] = '0006_ensure_unique_constraints'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        op.add_column('food_items', sa.Column('category', sa.Text(), nullable=True))
        op.create_index('idx_food_items_category', 'food_items', ['category'])
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('food_items')}
    if 'category' not in columns:
        with op.batch_alter_table('food_items') as batch_op:
            batch_op.add_column(sa.Column('category', sa.Text(), nullable=True))

    indexes = {idx['name'] for idx in inspector.get_indexes('food_items')}
    if 'idx_food_items_category' not in indexes:
        op.create_index('idx_food_items_category', 'food_items', ['category'])


def downgrade() -> None:
    if context.is_offline_mode():
        op.drop_index('idx_food_items_category', table_name='food_items')
        op.drop_column('food_items', 'category')
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {idx['name'] for idx in inspector.get_indexes('food_items')}
    if 'idx_food_items_category' in indexes:
        op.drop_index('idx_food_items_category', table_name='food_items')

    columns = {col['name'] for col in inspector.get_columns('food_items')}
    if 'category' in columns:
        with op.batch_alter_table('food_items') as batch_op:
            batch_op.drop_column('category')
