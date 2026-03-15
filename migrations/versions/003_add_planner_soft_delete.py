"""add deleted_at column to planner_activity for soft delete

Enables soft delete: instead of physically removing rows,
they are marked with a timestamp. Rows with deleted_at IS NULL
are considered active.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = '003_planner_soft_delete'
down_revision: Union[str, Sequence[str], None] = '002_planner_cols'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    """Check if a column already exists (safe for re-runs)."""
    conn = op.get_bind()
    insp = inspect(conn)
    return column in [c["name"] for c in insp.get_columns(table)]


def upgrade() -> None:
    if not _column_exists("planner_activity", "deleted_at"):
        op.add_column(
            "planner_activity",
            sa.Column("deleted_at", sa.DateTime, nullable=True),
        )
        op.create_index(
            "ix_planner_activity_deleted_at",
            "planner_activity",
            ["deleted_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_planner_activity_deleted_at", table_name="planner_activity")
    op.drop_column("planner_activity", "deleted_at")
