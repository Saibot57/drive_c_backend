"""Convert family_member and activity tables to utf8mb4

Fixes broken emoji icons on family members. Tables created by
db.create_all() inherited the database default charset (utf8 / 3-byte)
which silently replaces 4-byte emoji with '?'.

Revision ID: 005_family_member_utf8mb4
Revises: 004_workspace_tables
Create Date: 2026-03-28
"""
from typing import Sequence, Union
from alembic import op

revision: str = '005_family_member_utf8mb4'
down_revision: Union[str, Sequence[str], None] = '004_workspace_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE family_member CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    op.execute("ALTER TABLE activity CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    op.execute("ALTER TABLE activity_participants CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")


def downgrade() -> None:
    pass  # no safe downgrade — would risk data loss
