"""Index de performance sur catalogue alimentaire (BALI-189).

Revision ID: 0005_perf_indexes
Revises: 0004_update_unique_constraints
Create Date: 2026-11-03 14:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0005_perf_indexes'
down_revision: Union[str, Sequence[str], None] = '0004_update_unique_constraints'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Index pour recherche rapide et pagination sur les aliments (food_items.name)
    op.create_index('idx_food_items_name', 'food_items', ['name'])


def downgrade() -> None:
    op.drop_index('idx_food_items_name', table_name='food_items')
