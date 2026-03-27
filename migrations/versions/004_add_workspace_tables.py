"""Add workspace tables: surfaces, workspace_elements, surface_elements

Revision ID: 004_workspace_tables
Revises: 003_planner_soft_delete
Create Date: 2026-03-27
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '004_workspace_tables'
down_revision: Union[str, Sequence[str], None] = '003_planner_soft_delete'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'surfaces',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('name', sa.String(255), nullable=False, server_default='Untitled'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_surfaces_user_id', 'surfaces', ['user_id'])

    op.create_table(
        'workspace_elements',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('type', sa.String(20), nullable=False),
        sa.Column('title', sa.String(255), nullable=False, server_default='Untitled'),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_workspace_elements_user_id', 'workspace_elements', ['user_id'])

    op.create_table(
        'surface_elements',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('surface_id', sa.String(36), nullable=False),
        sa.Column('element_id', sa.String(36), nullable=False),
        sa.Column('position_x', sa.Float(), nullable=False, server_default='0'),
        sa.Column('position_y', sa.Float(), nullable=False, server_default='0'),
        sa.Column('width', sa.Float(), nullable=False, server_default='320'),
        sa.Column('height', sa.Float(), nullable=False, server_default='200'),
        sa.Column('is_locked', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('is_on_canvas', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('z_index', sa.Integer(), nullable=False, server_default='0'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_surface_elements_surface_id', 'surface_elements', ['surface_id'])
    op.create_index('ix_surface_elements_element_id', 'surface_elements', ['element_id'])


def downgrade() -> None:
    op.drop_index('ix_surface_elements_element_id', table_name='surface_elements')
    op.drop_index('ix_surface_elements_surface_id', table_name='surface_elements')
    op.drop_table('surface_elements')
    op.drop_index('ix_workspace_elements_user_id', table_name='workspace_elements')
    op.drop_table('workspace_elements')
    op.drop_index('ix_surfaces_user_id', table_name='surfaces')
    op.drop_table('surfaces')
