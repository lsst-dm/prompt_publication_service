# This file is part of prompt_publication_service.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from enum import IntEnum
from typing import Any, TypeAlias, Literal
from uuid import UUID
from datetime import datetime
from sqlalchemy import ForeignKeyConstraint, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
import sqlalchemy.types as types


class DatasetOrigin(IntEnum):
    """Service/process that this dataset originated from."""

    # These integer values are persisted in the database -- do not re-use
    # an integer value when making changes.

    PROMPT_PROCESSING = 1
    """Datasets created by prompt processing worker pods."""


class DatasetLocationStatus(IntEnum):
    """Enum representing the status of a dataset in a given repository."""

    # These integer values are persisted in the database -- do not re-use
    # an integer value when making changes.

    NEVER_PRESENT = 0
    """The dataset has never been stored in this location."""
    PRESENT = 1
    """The dataset is currently stored in this location."""
    MISSING = 2
    """The dataset was expected to be found in this location, but it is not
    present.
    """
    DELETED = 3
    """The dataset was formerly present in this location, but was intentionally
    deleted.
    """


class DimensionRecordStatus(IntEnum):
    """Enum representing the status of a set of dimension metadata records in a
    given repository.
    """

    # These integer values are persisted in the database -- do not re-use
    # an integer value when making changes.

    NEVER_PRESENT = 0
    """The dimension records have never been set up in this location."""
    INITIAL = 1
    """The dimension records in this location are based on the initial
    values read from the raw images.
    """
    REVISED = 2
    """The dimension records in this location have been updated with revised
    values from `visit_geometry` datasets.
    """


class _EnumColumn[T: IntEnum](types.TypeDecorator):
    """SQLAlchemy column type for storing an ``IntEnum`` value in the DB as a
    SMALLINT value.
    """

    impl = types.SmallInteger
    cache_ok = True

    def __init__(self, enum_type: type[T]) -> None:
        super().__init__()
        self._enum_type = enum_type

    def process_bind_param(self, value: Any | None, dialect: object) -> int | None:
        if value is None:
            return None
        return int(value)

    def process_result_value(self, value: int | None, dialect: object) -> T | None:
        if value is None:
            return None
        return self._enum_type(value)


class Base(DeclarativeBase):
    """SQLAlchemy ORM root class."""

    pass


ButlerRepository: TypeAlias = Literal[
    "embargo", "prompt_prep", "/repo/main", "prompt_google_int", "prompt_google_prod"
]

_butler_repository_to_status_column: dict[ButlerRepository, str] = {
    "embargo": "embargo_status",
    "prompt_prep": "prompt_prep_status",
    "/repo/main": "repo_main_status",
    "prompt_google_int": "google_int_status",
    "prompt_google_prod": "google_prod_status",
}


def _dimension_status_column(
    default: DimensionRecordStatus = DimensionRecordStatus.NEVER_PRESENT,
) -> Mapped[DimensionRecordStatus]:
    return mapped_column(_EnumColumn(DimensionRecordStatus), default=default, index=True)


class DimensionRecordTableMixin:
    """Columns that are used in both the `Visit` and `Exposure tables."""

    id: Mapped[int] = mapped_column(types.BigInteger, primary_key=True)
    """Dimension primary key from the Butler (visit or exposure)."""
    instrument: Mapped[str] = mapped_column(primary_key=True)
    """Instrument name from the Butler."""
    day_obs: Mapped[int] = mapped_column(types.BigInteger)
    """Observation date as stored in the Butler.  Note that this is the local
    date at the beginning of the observing night, and not necessarily the same
    calendar date as the exposure time below.
    """
    time: Mapped[datetime | None]
    """Date and time when the visit/exposure ended."""

    embargo_status = _dimension_status_column(DimensionRecordStatus.INITIAL)
    """Status of these dimension records in the ``embargo`` Butler
    repository."""
    prompt_prep_status = _dimension_status_column()
    """Status of these dimension records in the ``prompt_prep`` Butler
    repository."""
    repo_main_status = _dimension_status_column()
    """Status of these dimension records in the ``/repo/main`` Butler
    repository."""
    google_int_status = _dimension_status_column()
    """Status of these dimension records in the ``prompt`` Butler repository on
    the Google RSP integration testing environment.  """
    google_prod_status = _dimension_status_column()
    """Status of these dimension records in the ``prompt`` Butler repository on
    the Google RSP production environment.  """

    @classmethod
    def get_status_column(cls, repository: ButlerRepository) -> Mapped[DimensionRecordStatus]:
        return getattr(cls, cls.get_status_column_name(repository))

    @classmethod
    def get_status_column_name(cls, repository: ButlerRepository) -> str:
        return _butler_repository_to_status_column[repository]


class Visit(DimensionRecordTableMixin, Base):
    """Table tracking the status of Butler `visit` dimension metadata."""

    __tablename__ = "visit"


class Exposure(DimensionRecordTableMixin, Base):
    """Table tracking the status of Butler `exposure` dimension metadata."""

    __tablename__ = "exposure"

    can_see_sky: Mapped[bool]
    """`True` if this exposure contains on-sky data. `False` if it contains
    only in-dome calibration or similar data that is not subject to embargo
    restrictions.
    """


class Dataset(Base):
    """Table tracking the datasets that are available for unembargo and
    publication.
    """

    __tablename__ = "dataset"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    """Butler Dataset UUID."""
    origin: Mapped[DatasetOrigin] = mapped_column(_EnumColumn(DatasetOrigin))
    """Which system/process generated this data."""
    dataset_type: Mapped[str]
    """Name of Butler DatasetType."""
    instrument: Mapped[str] = mapped_column(nullable=True)
    """Instrument name from the Butler."""
    visit: Mapped[int] = mapped_column(types.BigInteger, nullable=True)
    """Visit ID from the Butler."""
    exposure: Mapped[int] = mapped_column(types.BigInteger, nullable=True)
    """Exposure ID from the Butler."""

    embargo_status: Mapped[DatasetLocationStatus] = mapped_column(_EnumColumn(DatasetLocationStatus))
    """Status of this dataset in the ``embargo`` Butler repository."""
    prompt_prep_status: Mapped[DatasetLocationStatus] = mapped_column(
        _EnumColumn(DatasetLocationStatus), default=DatasetLocationStatus.NEVER_PRESENT
    )
    """Status of this dataset in the ``prompt_prep`` Butler repository."""
    repo_main_status: Mapped[DatasetLocationStatus] = mapped_column(
        _EnumColumn(DatasetLocationStatus), default=DatasetLocationStatus.NEVER_PRESENT
    )
    """Status of this dataset in the ``/repo/main`` Butler repository."""
    google_int_status: Mapped[DatasetLocationStatus] = mapped_column(
        _EnumColumn(DatasetLocationStatus), default=DatasetLocationStatus.NEVER_PRESENT
    )
    """Status of this dataset in the ``prompt`` Butler repository on the Google
    RSP integration testing environment.
    """
    google_prod_status: Mapped[DatasetLocationStatus] = mapped_column(
        _EnumColumn(DatasetLocationStatus), default=DatasetLocationStatus.NEVER_PRESENT
    )
    """Status of this dataset in the ``prompt`` Butler repository on the Google
    RSP production environment.
    """

    unembargo_time: Mapped[datetime | None]
    """Time when the dataset was copied out of embargo into the prompt_prep
    Butler repository.
    """

    __table_args__ = (
        ForeignKeyConstraint(["visit", "instrument"], ["visit.id", "visit.instrument"]),
        ForeignKeyConstraint(["exposure", "instrument"], ["exposure.id", "exposure.instrument"]),
        # For queries trying to determine which datasets need to be transferred
        # from one repository or another, we always have equality constraints
        # on dataset_type (because rules are defined on a per-dataset-type
        # basis) and prompt_prep_status (because prompt_prep is the 'central'
        # repository which is always involved in transfers.)
        #
        # We have an index for each repository status, to make sure these
        # searches stay fast as the DB grows.  This might be overkill, but I'm
        # not sure at this point what the right tradeoff is between disk space
        # vs consistency/reliability of Postgres' query planning, so I'm
        # leaning towards the latter.
        *(
            Index(f"{column}_lookup", column, "prompt_prep_status", "dataset_type")
            for column in (
                "embargo_status",
                "repo_main_status",
                "google_prod_status",
                "google_int_status",
            )
        ),
    )

    @classmethod
    def get_status_column(cls, repository: ButlerRepository) -> Mapped[DatasetLocationStatus]:
        return getattr(cls, cls.get_status_column_name(repository))

    @classmethod
    def get_status_column_name(cls, repository: ButlerRepository) -> str:
        return _butler_repository_to_status_column[repository]


class UnknownDataset(Base):
    """Table storing a list of datasets that we were instructed to register in
    the database, but which were not available in the original repository when
    we attempted to look them up.
    """

    __tablename__ = "unknown_dataset"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    """Butler Dataset UUID."""
    origin: Mapped[DatasetOrigin] = mapped_column(_EnumColumn(DatasetOrigin))
    """Which system/process generated this data."""
    error: Mapped[str]
    """Human readable string describing why this dataset is being tracked in
    this table.
    """


for table in (Dataset, Visit, Exposure):
    for status_column in _butler_repository_to_status_column.values():
        if getattr(table, status_column, None) is None:
            raise AssertionError(f"Table {table.__tablename__} is missing status column {status_column}")
