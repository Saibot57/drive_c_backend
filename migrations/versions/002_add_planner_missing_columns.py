"""add missing columns to planner_activity and planner_course

The planner tables were created by db.create_all() before
category and archive_name were added to the models.
db.create_all() does not alter existing tables, so these
columns are missing in production MySQL.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = '002_planner_cols'
down_revision: Union[str, Sequence[str], None] = '001_command_center'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    """Check if a column already exists (safe for re-runs)."""
    conn = op.get_bind()
    insp = inspect(conn)
    return column in [c["name"] for c in insp.get_columns(table)]


def upgrade() -> None:
    # planner_activity — add category and archive_name if missing
    if not _column_exists("planner_activity", "category"):
        op.add_column(
            "planner_activity",
            sa.Column("category", sa.String(255), nullable=True),
        )

    if not _column_exists("planner_activity", "archive_name"):
        op.add_column(
            "planner_activity",
            sa.Column("archive_name", sa.String(150), nullable=True),
        )

    # planner_course — add category if missing
    if not _column_exists("planner_course", "category"):
        op.add_column(
            "planner_course",
            sa.Column("category", sa.String(255), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("planner_course", "category")
    op.drop_column("planner_activity", "archive_name")
    op.drop_column("planner_activity", "category")
