"""Add tables for daytime AP publication

Revision ID: cfd2f982c01a
Revises: 1a4375d164e2
Create Date: 2026-11-13 16:46:47.804195

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cfd2f982c01a"
down_revision: str | Sequence[str] | None = "1a4375d164e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""

    # Create day_obs table and populate it from day_obs values recorded for
    # existing visits.
    op.create_table(
        "day_obs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("daytime_ap_status", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_day_obs")),
    )
    op.execute(
        sa.text("""
        INSERT INTO day_obs (id, daytime_ap_status)
        SELECT DISTINCT day_obs, 0 from visit
    """)
    )
    # Add a foreign key constraint for day_obs on the visit table.
    op.create_index(op.f("ix_visit_day_obs"), "visit", ["day_obs"], unique=False)
    op.create_foreign_key(op.f("fk_visit_day_obs_day_obs"), "visit", "day_obs", ["day_obs"], ["id"])

    # Add the publishable_dataset table.
    op.create_table(
        "publishable_dataset",
        sa.Column("day_obs", sa.BigInteger(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["dataset.id"], name=op.f("fk_publishable_dataset_dataset_id_dataset")
        ),
        sa.ForeignKeyConstraint(
            ["day_obs"], ["day_obs.id"], name=op.f("fk_publishable_dataset_day_obs_day_obs")
        ),
        sa.PrimaryKeyConstraint("day_obs", "dataset_id", name=op.f("pk_publishable_dataset")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("fk_visit_day_obs_day_obs"), "visit", type_="foreignkey")
    op.drop_index(op.f("ix_visit_day_obs"), table_name="visit")
    op.drop_table("publishable_dataset")
    op.drop_table("day_obs")
