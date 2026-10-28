"""add_friendships_table

Revision ID: e51b5ce69a60
Revises: 0002_enriched_biometrics
Create Date: 2026-10-28 11:29:02.409824

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e51b5ce69a60'
down_revision: Union[str, Sequence[str], None] = '0002_enriched_biometrics'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'friendships',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('friend_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.Text(), nullable=False, server_default='pending'),
        sa.Column('permission', sa.Text(), nullable=False, server_default='read_only'),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.Text(), nullable=False),
        sa.UniqueConstraint('user_id', 'friend_user_id', name='uq_friendships_user_friend')
    )
    op.create_index('idx_friendships_user', 'friendships', ['user_id'])
    op.create_index('idx_friendships_friend', 'friendships', ['friend_user_id'])
    op.create_index('idx_friendships_status', 'friendships', ['status'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_friendships_status', table_name='friendships')
    op.drop_index('idx_friendships_friend', table_name='friendships')
    op.drop_index('idx_friendships_user', table_name='friendships')
    op.drop_table('friendships')
