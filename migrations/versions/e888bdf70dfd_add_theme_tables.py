"""add theme tables

Revision ID: e888bdf70dfd
Revises: 002_planner_cols
Create Date: 2026-03-14

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e888bdf70dfd'
down_revision = '002_planner_cols'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('user_themes',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('tokens', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_user_themes_user_id'), 'user_themes', ['user_id'], unique=True)

    op.create_table('theme_presets',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('tokens', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_theme_presets_user_id'), 'theme_presets', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_theme_presets_user_id'), table_name='theme_presets')
    op.drop_table('theme_presets')
    op.drop_index(op.f('ix_user_themes_user_id'), table_name='user_themes')
    op.drop_table('user_themes')
