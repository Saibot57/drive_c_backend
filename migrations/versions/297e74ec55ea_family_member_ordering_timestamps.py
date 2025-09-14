"""family member ordering + timestamps"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '297e74ec55ea'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('family_member', sa.Column('display_order', sa.Integer(), nullable=True))
    op.add_column('family_member', sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')))
    op.add_column('family_member', sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')))
    op.alter_column('family_member', 'icon', type_=sa.String(length=32))
    op.create_index('ix_family_member_user_name', 'family_member', ['user_id', 'name'], unique=False)
    op.create_unique_constraint('uq_family_member_user_name', 'family_member', ['user_id', 'name'])


def downgrade() -> None:
    op.drop_constraint('uq_family_member_user_name', 'family_member', type_='unique')
    op.drop_index('ix_family_member_user_name', table_name='family_member')
    op.alter_column('family_member', 'icon', type_=sa.String(length=10))
    op.drop_column('family_member', 'updated_at')
    op.drop_column('family_member', 'created_at')
    op.drop_column('family_member', 'display_order')
