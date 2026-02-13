"""Initial schema

Revision ID: b59eced2ad76
Revises:
Create Date: 2026-01-26 16:09:26.375376

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b59eced2ad76"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "exposure",
        sa.Column("can_see_sky", sa.Boolean(), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("instrument", sa.String(), nullable=False),
        sa.Column("day_obs", sa.BigInteger(), nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embargo_status", sa.SmallInteger(), nullable=True),
        sa.Column("prompt_prep_status", sa.SmallInteger(), nullable=True),
        sa.Column("repo_main_status", sa.SmallInteger(), nullable=True),
        sa.Column("google_int_status", sa.SmallInteger(), nullable=True),
        sa.Column("google_prod_status", sa.SmallInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id", "instrument"),
    )
    op.create_index(op.f("ix_exposure_embargo_status"), "exposure", ["embargo_status"], unique=False)
    op.create_index(op.f("ix_exposure_google_int_status"), "exposure", ["google_int_status"], unique=False)
    op.create_index(op.f("ix_exposure_google_prod_status"), "exposure", ["google_prod_status"], unique=False)
    op.create_index(op.f("ix_exposure_prompt_prep_status"), "exposure", ["prompt_prep_status"], unique=False)
    op.create_index(op.f("ix_exposure_repo_main_status"), "exposure", ["repo_main_status"], unique=False)
    op.create_table(
        "group",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("instrument", sa.String(), nullable=False),
        sa.Column("embargo_status", sa.SmallInteger(), nullable=True),
        sa.Column("prompt_prep_status", sa.SmallInteger(), nullable=True),
        sa.Column("repo_main_status", sa.SmallInteger(), nullable=True),
        sa.Column("google_int_status", sa.SmallInteger(), nullable=True),
        sa.Column("google_prod_status", sa.SmallInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id", "instrument"),
    )
    op.create_index(op.f("ix_group_embargo_status"), "group", ["embargo_status"], unique=False)
    op.create_index(op.f("ix_group_google_int_status"), "group", ["google_int_status"], unique=False)
    op.create_index(op.f("ix_group_google_prod_status"), "group", ["google_prod_status"], unique=False)
    op.create_index(op.f("ix_group_prompt_prep_status"), "group", ["prompt_prep_status"], unique=False)
    op.create_index(op.f("ix_group_repo_main_status"), "group", ["repo_main_status"], unique=False)
    op.create_table(
        "unknown_dataset",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("origin", sa.SmallInteger(), nullable=False),
        sa.Column("error", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "visit",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("instrument", sa.String(), nullable=False),
        sa.Column("day_obs", sa.BigInteger(), nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embargo_status", sa.SmallInteger(), nullable=True),
        sa.Column("prompt_prep_status", sa.SmallInteger(), nullable=True),
        sa.Column("repo_main_status", sa.SmallInteger(), nullable=True),
        sa.Column("google_int_status", sa.SmallInteger(), nullable=True),
        sa.Column("google_prod_status", sa.SmallInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id", "instrument"),
    )
    op.create_index(op.f("ix_visit_embargo_status"), "visit", ["embargo_status"], unique=False)
    op.create_index(op.f("ix_visit_google_int_status"), "visit", ["google_int_status"], unique=False)
    op.create_index(op.f("ix_visit_google_prod_status"), "visit", ["google_prod_status"], unique=False)
    op.create_index(op.f("ix_visit_prompt_prep_status"), "visit", ["prompt_prep_status"], unique=False)
    op.create_index(op.f("ix_visit_repo_main_status"), "visit", ["repo_main_status"], unique=False)
    op.create_table(
        "dataset",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("origin", sa.SmallInteger(), nullable=False),
        sa.Column("dataset_type", sa.String(), nullable=False),
        sa.Column("instrument", sa.String(), nullable=True),
        sa.Column("visit", sa.BigInteger(), nullable=True),
        sa.Column("exposure", sa.BigInteger(), nullable=True),
        sa.Column("group", sa.String(), nullable=True),
        sa.Column("butler_data_id", sa.JSON(), nullable=True),
        sa.Column("embargo_status", sa.SmallInteger(), nullable=False),
        sa.Column("prompt_prep_status", sa.SmallInteger(), nullable=False),
        sa.Column("repo_main_status", sa.SmallInteger(), nullable=False),
        sa.Column("google_int_status", sa.SmallInteger(), nullable=False),
        sa.Column("google_prod_status", sa.SmallInteger(), nullable=False),
        sa.Column("unembargo_time", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["exposure", "instrument"],
            ["exposure.id", "exposure.instrument"],
        ),
        sa.ForeignKeyConstraint(
            ["group", "instrument"],
            ["group.id", "group.instrument"],
        ),
        sa.ForeignKeyConstraint(
            ["visit", "instrument"],
            ["visit.id", "visit.instrument"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "dataset_embargo_status_lookup",
        "dataset",
        ["embargo_status", "prompt_prep_status", "origin", "dataset_type"],
        unique=False,
    )
    op.create_index(
        "dataset_google_int_status_lookup",
        "dataset",
        ["google_int_status", "prompt_prep_status", "origin", "dataset_type"],
        unique=False,
    )
    op.create_index(
        "dataset_google_prod_status_lookup",
        "dataset",
        ["google_prod_status", "prompt_prep_status", "origin", "dataset_type"],
        unique=False,
    )
    op.create_index(
        "dataset_repo_main_status_lookup",
        "dataset",
        ["repo_main_status", "prompt_prep_status", "origin", "dataset_type"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("dataset_repo_main_status_lookup", table_name="dataset")
    op.drop_index("dataset_google_prod_status_lookup", table_name="dataset")
    op.drop_index("dataset_google_int_status_lookup", table_name="dataset")
    op.drop_index("dataset_embargo_status_lookup", table_name="dataset")
    op.drop_table("dataset")
    op.drop_index(op.f("ix_visit_repo_main_status"), table_name="visit")
    op.drop_index(op.f("ix_visit_prompt_prep_status"), table_name="visit")
    op.drop_index(op.f("ix_visit_google_prod_status"), table_name="visit")
    op.drop_index(op.f("ix_visit_google_int_status"), table_name="visit")
    op.drop_index(op.f("ix_visit_embargo_status"), table_name="visit")
    op.drop_table("visit")
    op.drop_table("unknown_dataset")
    op.drop_index(op.f("ix_group_repo_main_status"), table_name="group")
    op.drop_index(op.f("ix_group_prompt_prep_status"), table_name="group")
    op.drop_index(op.f("ix_group_google_prod_status"), table_name="group")
    op.drop_index(op.f("ix_group_google_int_status"), table_name="group")
    op.drop_index(op.f("ix_group_embargo_status"), table_name="group")
    op.drop_table("group")
    op.drop_index(op.f("ix_exposure_repo_main_status"), table_name="exposure")
    op.drop_index(op.f("ix_exposure_prompt_prep_status"), table_name="exposure")
    op.drop_index(op.f("ix_exposure_google_prod_status"), table_name="exposure")
    op.drop_index(op.f("ix_exposure_google_int_status"), table_name="exposure")
    op.drop_index(op.f("ix_exposure_embargo_status"), table_name="exposure")
    op.drop_table("exposure")
