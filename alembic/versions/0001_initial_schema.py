"""initial_schema

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-10-25 08:35:00.000000

Canonique VitalTrack Schema:
Tables: users, user_profile, weights, activities, meals, food_items, meal_logs, meal_log_items, saved_meals, user_devices, google_auth_config, google_sessions, nutrition_benefits, food_item_benefits.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001_initial_schema'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. users
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('uuid', sa.Text(), nullable=False, unique=True),
        sa.Column('email', sa.Text(), nullable=False, unique=True),
        sa.Column('password_hash', sa.Text(), nullable=True),
        sa.Column('auth_provider', sa.Text(), nullable=False, server_default='google'),
        sa.Column('google_sub', sa.Text(), nullable=True, unique=True),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('picture', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.Text(), nullable=False),
    )

    # 2. user_profile
    op.create_table(
        'user_profile',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('name', sa.Text(), nullable=False, server_default='Sébastien'),
        sa.Column('gender', sa.Text(), nullable=False, server_default='male'),
        sa.Column('age', sa.Integer(), nullable=False, server_default='35'),
        sa.Column('height_cm', sa.Float(), nullable=False, server_default='178.0'),
        sa.Column('target_weight_kg', sa.Float(), nullable=False, server_default='77.0'),
        sa.Column('goal_profile_id', sa.Text(), nullable=False, server_default='weight_loss'),
        sa.Column('target_steps', sa.Integer(), nullable=False, server_default='10000'),
        sa.Column('target_calories_intake', sa.Float(), nullable=False, server_default='2000.0'),
        sa.Column('protein_target_per_kg', sa.Float(), nullable=False, server_default='1.8'),
        sa.Column('daily_protein_target_g', sa.Float(), nullable=True),
        sa.Column('daily_carbs_target_g', sa.Float(), nullable=True),
        sa.Column('daily_fat_target_g', sa.Float(), nullable=True),
        sa.Column('daily_water_target_ml', sa.Float(), nullable=True, server_default='2000.0'),
        sa.Column('goal_type', sa.Text(), nullable=True, server_default='weight_loss'),
        sa.Column('activity_level', sa.Text(), nullable=True, server_default='moderately_active'),
        sa.Column('birth_date', sa.Text(), nullable=True),
        sa.Column('current_weight_kg', sa.Float(), nullable=True),
        sa.Column('meal_distribution', sa.Text(), nullable=True),
        sa.Column('preferred_ring', sa.Text(), nullable=True, server_default='ringconn'),
        sa.Column('preferred_scale', sa.Text(), nullable=True, server_default='withings'),
        sa.Column('google_email', sa.Text(), nullable=True),
        sa.Column('google_name', sa.Text(), nullable=True),
        sa.Column('google_picture', sa.Text(), nullable=True),
        sa.Column('google_sub', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.Text(), nullable=False),
    )

    # 3. weights
    op.create_table(
        'weights',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Text(), nullable=False),
        sa.Column('weight_kg', sa.Float(), nullable=False),
        sa.Column('body_fat_pct', sa.Float(), nullable=True),
        sa.Column('muscle_mass_kg', sa.Float(), nullable=True),
        sa.Column('water_pct', sa.Float(), nullable=True),
        sa.Column('bmi', sa.Float(), nullable=True),
        sa.Column('trend_7d_kg', sa.Float(), nullable=True),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.UniqueConstraint('user_id', 'date', name='uq_weights_user_date'),
    )
    op.create_index('idx_weights_user_date', 'weights', ['user_id', 'date'])

    # 4. activities
    op.create_table(
        'activities',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Text(), nullable=False),
        sa.Column('steps', sa.Integer(), nullable=False),
        sa.Column('active_calories_kcal', sa.Float(), nullable=False),
        sa.Column('bmr_kcal', sa.Float(), nullable=False),
        sa.Column('total_burned_kcal', sa.Float(), nullable=False),
        sa.Column('workout_minutes', sa.Integer(), nullable=False),
        sa.Column('workout_type', sa.Text(), nullable=True),
        sa.Column('resting_hr_bpm', sa.Integer(), nullable=True),
        sa.Column('hrv_ms', sa.Float(), nullable=True),
        sa.Column('sleep_score', sa.Integer(), nullable=True),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.UniqueConstraint('user_id', 'date', name='uq_activities_user_date'),
    )
    op.create_index('idx_activities_user_date', 'activities', ['user_id', 'date'])

    # 5. meals
    op.create_table(
        'meals',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Text(), nullable=False),
        sa.Column('meal_type', sa.Text(), nullable=False),
        sa.Column('total_calories_kcal', sa.Float(), nullable=False),
        sa.Column('protein_g', sa.Float(), nullable=False),
        sa.Column('carbs_g', sa.Float(), nullable=False),
        sa.Column('fat_g', sa.Float(), nullable=False),
        sa.Column('fiber_g', sa.Float(), nullable=True),
        sa.Column('photo_data_url', sa.Text(), nullable=True),
        sa.Column('items_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False),
    )
    op.create_index('idx_meals_user_date', 'meals', ['user_id', 'date', 'id'])

    # 6. food_items
    op.create_table(
        'food_items',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('item_type', sa.Text(), nullable=False, server_default='food'),
        sa.Column('default_unit', sa.Text(), nullable=False, server_default='g'),
        sa.Column('default_quantity', sa.Float(), nullable=False, server_default='100.0'),
        sa.Column('calories_per_unit', sa.Float(), nullable=False),
        sa.Column('protein_per_unit_g', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('carbs_per_unit_g', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('fat_per_unit_g', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('fiber_per_unit_g', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('photo_url', sa.Text(), nullable=True),
        sa.Column('recipe_items_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.Text(), nullable=False),
    )
    op.create_index('idx_food_items_user', 'food_items', ['user_id', 'item_type'])

    # 7. meal_logs
    op.create_table(
        'meal_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Text(), nullable=False),
        sa.Column('meal_type', sa.Text(), nullable=False),
        sa.Column('photo_url', sa.Text(), nullable=True),
        sa.Column('total_calories', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('total_protein_g', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('total_carbs_g', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('total_fat_g', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('total_fiber_g', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.Text(), nullable=False),
        sa.UniqueConstraint('user_id', 'date', 'meal_type', name='uq_meal_logs_user_date_type'),
    )
    op.create_index('idx_meal_logs_user_date', 'meal_logs', ['user_id', 'date'])

    # 8. meal_log_items
    op.create_table(
        'meal_log_items',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('meal_log_id', sa.Integer(), sa.ForeignKey('meal_logs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('food_item_id', sa.Integer(), sa.ForeignKey('food_items.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('unit', sa.Text(), nullable=False, server_default='g'),
        sa.Column('calories', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('protein_g', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('carbs_g', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('fat_g', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('fiber_g', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('created_at', sa.Text(), nullable=False),
    )
    op.create_index('idx_meal_log_items_meal', 'meal_log_items', ['meal_log_id'])

    # 9. saved_meals
    op.create_table(
        'saved_meals',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('meal_type', sa.Text(), nullable=False, server_default='lunch'),
        sa.Column('serving_size', sa.Text(), nullable=True, server_default='1 portion'),
        sa.Column('quantity_grams', sa.Float(), nullable=True),
        sa.Column('calories', sa.Float(), nullable=False),
        sa.Column('protein_g', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('carbs_g', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('fat_g', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('fiber_g', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('ingredients', sa.Text(), nullable=True),
        sa.Column('items_json', sa.Text(), nullable=True),
        sa.Column('photo_url', sa.Text(), nullable=True),
        sa.Column('is_favorite', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.Text(), nullable=False),
    )
    op.create_index('idx_saved_meals_user_type', 'saved_meals', ['user_id', 'meal_type'])

    # 10. user_devices
    op.create_table(
        'user_devices',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('device_id', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('device_type', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('connected', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('auth_type', sa.Text(), nullable=False, server_default='demo'),
        sa.Column('api_key', sa.Text(), nullable=True),
        sa.Column('encrypted_credentials', sa.Text(), nullable=True),
        sa.Column('account_email', sa.Text(), nullable=True),
        sa.Column('last_sync', sa.Text(), nullable=True),
        sa.Column('last_sync_at', sa.Text(), nullable=True),
        sa.Column('sync_status', sa.Text(), nullable=True, server_default='disconnected'),
        sa.Column('updated_at', sa.Text(), nullable=False),
        sa.UniqueConstraint('user_id', 'device_id', name='uq_user_devices_user_device'),
    )

    # 11. google_auth_config
    op.create_table(
        'google_auth_config',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('google_client_id', sa.Text(), nullable=False, server_default=''),
        sa.Column('updated_at', sa.Text(), nullable=False),
    )

    # 12. google_sessions
    op.create_table(
        'google_sessions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('email', sa.Text(), nullable=False, unique=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('picture', sa.Text(), nullable=True),
        sa.Column('google_sub', sa.Text(), nullable=True),
        sa.Column('auth_method', sa.Text(), nullable=False, server_default='google'),
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('last_login', sa.Text(), nullable=False),
    )

    # 13. nutrition_benefits
    op.create_table(
        'nutrition_benefits',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('category', sa.Text(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('icon', sa.Text(), nullable=False),
        sa.Column('rule_config', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False),
    )
    op.create_index('idx_nutrition_benefits_cat', 'nutrition_benefits', ['category_id'])

    # 14. food_item_benefits
    op.create_table(
        'food_item_benefits',
        sa.Column('food_item_id', sa.Integer(), sa.ForeignKey('food_items.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('benefit_id', sa.Text(), sa.ForeignKey('nutrition_benefits.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('source', sa.Text(), nullable=False, server_default='manual'),
        sa.Column('explanation', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False),
    )
    op.create_index('idx_food_item_benefits_food', 'food_item_benefits', ['food_item_id'])


def downgrade() -> None:
    op.drop_table('food_item_benefits')
    op.drop_table('nutrition_benefits')
    op.drop_table('google_sessions')
    op.drop_table('google_auth_config')
    op.drop_table('user_devices')
    op.drop_table('saved_meals')
    op.drop_table('meal_log_items')
    op.drop_table('meal_logs')
    op.drop_table('food_items')
    op.drop_table('meals')
    op.drop_table('activities')
    op.drop_table('weights')
    op.drop_table('user_profile')
    op.drop_table('users')
