"""add_food_items_barcode_nutriscore

Revision ID: 0008_add_food_items_barcode_nutriscore
Revises: 0007_add_food_items_category
Create Date: 2026-11-22 22:30:00.000000

BALI-295 : Ajoute barcode et nutriscore sur food_items pour le scanner OpenFoodFacts.
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008_add_food_items_barcode_nutriscore'
down_revision: Union[str, Sequence[str], None] = '0007_add_food_items_category'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        op.add_column('food_items', sa.Column('barcode', sa.Text(), nullable=True))
        op.add_column('food_items', sa.Column('nutriscore', sa.Text(), nullable=True))
        op.create_index('idx_food_items_barcode', 'food_items', ['barcode'])
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('food_items')}
    with op.batch_alter_table('food_items') as batch_op:
        if 'barcode' not in columns:
            batch_op.add_column(sa.Column('barcode', sa.Text(), nullable=True))
        if 'nutriscore' not in columns:
            batch_op.add_column(sa.Column('nutriscore', sa.Text(), nullable=True))

    indexes = {idx['name'] for idx in inspector.get_indexes('food_items')}
    if 'idx_food_items_barcode' not in indexes:
        op.create_index('idx_food_items_barcode', 'food_items', ['barcode'])


def downgrade() -> None:
    if context.is_offline_mode():
        op.drop_index('idx_food_items_barcode', table_name='food_items')
        op.drop_column('food_items', 'nutriscore')
        op.drop_column('food_items', 'barcode')
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {idx['name'] for idx in inspector.get_indexes('food_items')}
    if 'idx_food_items_barcode' in indexes:
        op.drop_index('idx_food_items_barcode', table_name='food_items')

    columns = {col['name'] for col in inspector.get_columns('food_items')}
    with op.batch_alter_table('food_items') as batch_op:
        if 'nutriscore' in columns:
            batch_op.drop_column('nutriscore')
        if 'barcode' in columns:
            batch_op.drop_column('barcode')
