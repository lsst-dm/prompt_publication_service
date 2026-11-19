"""Eliminate dataset origin

Revision ID: 1a4375d164e2
Revises: 493b6fe5abba
Create Date: 2026-11-09 10:20:54.278601

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1a4375d164e2"
down_revision: str | Sequence[str] | None = "493b6fe5abba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove the dataset origin column from ``dataset`` and
    ``unknown_dataset`` tables, and modify all indexes involving it to remove
    it.
    """
    op.drop_index(op.f("dataset_embargo_status_lookup"), table_name="dataset")
    op.create_index(
        "dataset_embargo_status_lookup",
        "dataset",
        ["embargo_status", "prompt_prep_status", "dataset_type"],
        unique=False,
    )
    op.drop_index(op.f("dataset_google_int_status_lookup"), table_name="dataset")
    op.create_index(
        "dataset_google_int_status_lookup",
        "dataset",
        ["google_int_status", "prompt_prep_status", "dataset_type"],
        unique=False,
    )
    op.drop_index(op.f("dataset_google_prod_status_lookup"), table_name="dataset")
    op.create_index(
        "dataset_google_prod_status_lookup",
        "dataset",
        ["google_prod_status", "prompt_prep_status", "dataset_type"],
        unique=False,
    )
    op.drop_index(op.f("dataset_repo_main_status_lookup"), table_name="dataset")
    op.create_index(
        "dataset_repo_main_status_lookup",
        "dataset",
        ["repo_main_status", "prompt_prep_status", "dataset_type"],
        unique=False,
    )
    op.drop_column("dataset", "origin")
    op.drop_column("unknown_dataset", "origin")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("unknown_dataset", sa.Column("origin", sa.SMALLINT(), autoincrement=False, nullable=False))
    op.add_column("dataset", sa.Column("origin", sa.SMALLINT(), autoincrement=False, nullable=False))
    op.drop_index("dataset_repo_main_status_lookup", table_name="dataset")
    op.create_index(
        op.f("dataset_repo_main_status_lookup"),
        "dataset",
        ["repo_main_status", "prompt_prep_status", "origin", "dataset_type"],
        unique=False,
    )
    op.drop_index("dataset_google_prod_status_lookup", table_name="dataset")
    op.create_index(
        op.f("dataset_google_prod_status_lookup"),
        "dataset",
        ["google_prod_status", "prompt_prep_status", "origin", "dataset_type"],
        unique=False,
    )
    op.drop_index("dataset_google_int_status_lookup", table_name="dataset")
    op.create_index(
        op.f("dataset_google_int_status_lookup"),
        "dataset",
        ["google_int_status", "prompt_prep_status", "origin", "dataset_type"],
        unique=False,
    )
    op.drop_index("dataset_embargo_status_lookup", table_name="dataset")
    op.create_index(
        op.f("dataset_embargo_status_lookup"),
        "dataset",
        ["embargo_status", "prompt_prep_status", "origin", "dataset_type"],
        unique=False,
    )
