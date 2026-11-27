"""add_user_profile_nutrition_goals_config

Revision ID: 0009_add_user_profile_nutrition_goals_config
Revises: 0008_add_food_items_barcode_nutriscore
Create Date: 2026-11-27 07:25:00.000000

BALI-303 : Ajoute la colonne JSON nutrition_goals_config sur user_profile pour
stocker les règles configurables par nutriment (seuil plancher, plafond, fourchette).
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009_add_user_profile_nutrition_goals_config'
down_revision: Union[str, Sequence[str], None] = '0008_add_food_items_barcode_nutriscore'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        op.add_column('user_profile', sa.Column('nutrition_goals_config', sa.Text(), nullable=True))
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('user_profile')}
    if 'nutrition_goals_config' not in columns:
        with op.batch_alter_table('user_profile') as batch_op:
            batch_op.add_column(sa.Column('nutrition_goals_config', sa.Text(), nullable=True))


def downgrade() -> None:
    if context.is_offline_mode():
        op.drop_column('user_profile', 'nutrition_goals_config')
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('user_profile')}
    if 'nutrition_goals_config' in columns:
        with op.batch_alter_table('user_profile') as batch_op:
            batch_op.drop_column('nutrition_goals_config')
