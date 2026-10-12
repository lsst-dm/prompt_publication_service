"""Unify visit dimensions

Revision ID: 493b6fe5abba
Revises: b59eced2ad76
Create Date: 2026-10-12 10:27:28.613195

"""

import csv
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "493b6fe5abba"
down_revision: str | Sequence[str] | None = "b59eced2ad76"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema to remove exposure and group columns from the dataset
    table, and remove the group and exposure tables.

    Notes
    ----
    If you are running on a database that has existing data,
    run lsst.prompt_publication_service.scripts.generate_visit_conversion_table
    to generate the data/group_exposure_mapping.csv file before running this
    migration.
    """

    # Assign a value for 'visit' based on 'exposure'/'group' columns.
    # Exposure IDs and visit IDs are identical, but the visit ID corresponding
    # to group is unpredictable and must be looked up based on Butler metadata
    # that was exported to a CSV file.
    group_lookup = sa.Table(
        "group_lookup",
        sa.MetaData(),
        sa.Column("group", sa.String(), nullable=False, index=True),
        sa.Column("exposure", sa.BigInteger(), nullable=False),
        prefixes=["TEMPORARY"],
    )
    group_lookup.create(bind=op.get_bind())
    rows = _load_group_exposure_mapping()
    op.get_bind().execute(group_lookup.insert(), rows)
    op.execute("""
        UPDATE dataset
        SET visit = COALESCE(
            dataset.exposure,
            (SELECT group_lookup.exposure FROM group_lookup WHERE dataset.group = group_lookup.group)
        ),
            butler_data_id = (butler_data_id::jsonb ||
                jsonb_strip_nulls(jsonb_build_object('group', dataset.group, 'exposure', dataset.exposure))
            )::json
        WHERE dataset.visit IS NULL
        """)

    op.alter_column("dataset", "visit", existing_type=sa.BIGINT(), nullable=False)
    op.drop_constraint(op.f("dataset_exposure_instrument_fkey"), "dataset", type_="foreignkey")
    op.drop_constraint(op.f("dataset_group_instrument_fkey"), "dataset", type_="foreignkey")
    op.drop_column("dataset", "exposure")
    op.drop_column("dataset", "group")

    op.drop_index(op.f("ix_group_embargo_status"), table_name="group")
    op.drop_index(op.f("ix_group_google_int_status"), table_name="group")
    op.drop_index(op.f("ix_group_google_prod_status"), table_name="group")
    op.drop_index(op.f("ix_group_prompt_prep_status"), table_name="group")
    op.drop_index(op.f("ix_group_repo_main_status"), table_name="group")
    op.drop_table("group")
    op.drop_index(op.f("ix_exposure_embargo_status"), table_name="exposure")
    op.drop_index(op.f("ix_exposure_google_int_status"), table_name="exposure")
    op.drop_index(op.f("ix_exposure_google_prod_status"), table_name="exposure")
    op.drop_index(op.f("ix_exposure_prompt_prep_status"), table_name="exposure")
    op.drop_index(op.f("ix_exposure_repo_main_status"), table_name="exposure")
    op.drop_table("exposure")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("dataset", sa.Column("group", sa.VARCHAR(), autoincrement=False, nullable=True))
    op.add_column("dataset", sa.Column("exposure", sa.BIGINT(), autoincrement=False, nullable=True))
    op.create_foreign_key(
        op.f("dataset_group_instrument_fkey"),
        "dataset",
        "group",
        ["group", "instrument"],
        ["id", "instrument"],
    )
    op.create_foreign_key(
        op.f("dataset_exposure_instrument_fkey"),
        "dataset",
        "exposure",
        ["exposure", "instrument"],
        ["id", "instrument"],
    )
    op.alter_column("dataset", "visit", existing_type=sa.BIGINT(), nullable=True)
    op.create_table(
        "exposure",
        sa.Column("can_see_sky", sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.Column("id", sa.BIGINT(), autoincrement=False, nullable=False),
        sa.Column("instrument", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column("day_obs", sa.BIGINT(), autoincrement=False, nullable=False),
        sa.Column("time", postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True),
        sa.Column("embargo_status", sa.SMALLINT(), autoincrement=False, nullable=True),
        sa.Column("prompt_prep_status", sa.SMALLINT(), autoincrement=False, nullable=True),
        sa.Column("repo_main_status", sa.SMALLINT(), autoincrement=False, nullable=True),
        sa.Column("google_int_status", sa.SMALLINT(), autoincrement=False, nullable=True),
        sa.Column("google_prod_status", sa.SMALLINT(), autoincrement=False, nullable=True),
        sa.PrimaryKeyConstraint("id", "instrument", name=op.f("exposure_pkey")),
    )
    op.create_index(op.f("ix_exposure_repo_main_status"), "exposure", ["repo_main_status"], unique=False)
    op.create_index(op.f("ix_exposure_prompt_prep_status"), "exposure", ["prompt_prep_status"], unique=False)
    op.create_index(op.f("ix_exposure_google_prod_status"), "exposure", ["google_prod_status"], unique=False)
    op.create_index(op.f("ix_exposure_google_int_status"), "exposure", ["google_int_status"], unique=False)
    op.create_index(op.f("ix_exposure_embargo_status"), "exposure", ["embargo_status"], unique=False)
    op.create_table(
        "group",
        sa.Column("id", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column("instrument", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column("embargo_status", sa.SMALLINT(), autoincrement=False, nullable=True),
        sa.Column("prompt_prep_status", sa.SMALLINT(), autoincrement=False, nullable=True),
        sa.Column("repo_main_status", sa.SMALLINT(), autoincrement=False, nullable=True),
        sa.Column("google_int_status", sa.SMALLINT(), autoincrement=False, nullable=True),
        sa.Column("google_prod_status", sa.SMALLINT(), autoincrement=False, nullable=True),
        sa.PrimaryKeyConstraint("id", "instrument", name=op.f("group_pkey")),
    )
    op.create_index(op.f("ix_group_repo_main_status"), "group", ["repo_main_status"], unique=False)
    op.create_index(op.f("ix_group_prompt_prep_status"), "group", ["prompt_prep_status"], unique=False)
    op.create_index(op.f("ix_group_google_prod_status"), "group", ["google_prod_status"], unique=False)
    op.create_index(op.f("ix_group_google_int_status"), "group", ["google_int_status"], unique=False)
    op.create_index(op.f("ix_group_embargo_status"), "group", ["embargo_status"], unique=False)


def _load_group_exposure_mapping() -> list[dict[str, int | str]]:
    """Load the group-to-exposure mapping exported from Butler metadata."""
    csv_path = Path(__file__).parent.parent / "data" / "group_exposure_mapping.csv"
    with csv_path.open() as csv_file:
        return [{"group": row["Group"], "exposure": int(row["Exposure"])} for row in csv.DictReader(csv_file)]
