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

from datetime import datetime
from enum import IntEnum
from typing import Any, Literal, TypeAlias
from uuid import UUID

import sqlalchemy.types as types
from sqlalchemy import JSON, ForeignKey, ForeignKeyConstraint, Index, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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


class VisitPublicationStatus(IntEnum):
    """Enum representing the publication status of a visit in a given
    repository.
    """

    # These integer values are persisted in the database -- do not re-use
    # an integer value when making changes.

    NEVER_PRESENT = 0
    """The visit has never been published to this location."""
    PUBLISHED = 1
    """The visit has been published to this location."""
    INCOMPLETE = 2
    """Datasets required by publication were not generated, so this visit will
    not be published.
    """


class DaytimeApStatus(IntEnum):
    """Enum representing the status of Daytime AP processing."""

    # These integer values are persisted in the database -- do not re-use
    # an integer value when making changes.

    INCOMPLETE = 0
    """Daytime AP has not yet finished generating its datasets."""
    COMPLETED = 1
    """Daytime AP has run to completion and its outputs are finalized."""


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

    def __repr__(self) -> str:
        # This controls how the column is rendered when alembic is generating
        # migrations.
        return "SmallInteger()"


class Base(DeclarativeBase):
    """SQLAlchemy ORM root class."""

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


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


def _publication_status_column() -> Mapped[VisitPublicationStatus]:
    return mapped_column(
        _EnumColumn(VisitPublicationStatus), default=VisitPublicationStatus.NEVER_PRESENT, index=True
    )


class DayObs(Base):
    """Table tracking the status of processes that run on a per-day basis."""

    __tablename__ = "day_obs"

    id: Mapped[int] = mapped_column(types.Integer, primary_key=True)
    """Observation date as the day_obs dimension value from the Butler."""
    daytime_ap_status: Mapped[DaytimeApStatus] = mapped_column(
        _EnumColumn(DaytimeApStatus), default=DaytimeApStatus.INCOMPLETE
    )
    """Status of daytime AP processing for this day_obs."""


class Visit(Base):
    """Table tracking the status of Butler visits, both `visit` dimension
    metadata and publication status for the corresponding datasets.
    """

    __tablename__ = "visit"

    id: Mapped[int] = mapped_column(types.BigInteger, primary_key=True)
    """Dimension primary key from the Butler (visit or exposure)."""
    instrument: Mapped[str] = mapped_column(primary_key=True)
    """Instrument name from the Butler."""
    day_obs: Mapped[int] = mapped_column(types.BigInteger, ForeignKey("day_obs.id"))
    """Observation date as stored in the Butler.  Note that this is the local
    date at the beginning of the observing night, and not necessarily the same
    calendar date as the exposure time below.
    """
    time: Mapped[datetime | None] = mapped_column(types.DateTime(timezone=True), nullable=True)
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
    google_int_status = _publication_status_column()
    """Status of this visit's dimension records and associated datasets in the
    ``prompt`` Butler repository on the Google RSP integration testing
    environment.  """
    google_prod_status = _publication_status_column()
    """Status of these dimension records in the ``prompt`` Butler repository on
    the Google RSP production environment.  """

    @classmethod
    def get_status_column(cls, repository: ButlerRepository) -> Mapped[DimensionRecordStatus]:
        assert repository in ("embargo", "prompt_prep", "/repo/main")
        return getattr(cls, cls.get_status_column_name(repository))

    def set_status_column(self, repository: ButlerRepository, status: DimensionRecordStatus) -> None:
        assert repository in ("embargo", "prompt_prep", "/repo/main")
        setattr(self, self.get_status_column_name(repository), status)

    @classmethod
    def get_publication_status_column(cls, repository: ButlerRepository) -> Mapped[VisitPublicationStatus]:
        assert repository in ("prompt_google_int", "prompt_google_prod")
        return getattr(cls, cls.get_status_column_name(repository))

    def set_publication_status_column(
        self, repository: ButlerRepository, status: VisitPublicationStatus
    ) -> None:
        assert repository in ("prompt_google_int", "prompt_google_prod")
        setattr(self, self.get_status_column_name(repository), status)

    @classmethod
    def get_status_column_name(cls, repository: ButlerRepository) -> str:
        return _butler_repository_to_status_column[repository]


class Dataset(Base):
    """Table tracking the datasets that are available for unembargo and
    publication.
    """

    __tablename__ = "dataset"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    """Butler Dataset UUID."""
    dataset_type: Mapped[str]
    """Name of Butler DatasetType."""
    instrument: Mapped[str] = mapped_column(nullable=True)
    """Instrument name from the Butler."""
    visit: Mapped[int] = mapped_column(types.BigInteger)
    """Visit ID from the Butler."""
    butler_data_id: Mapped[dict[str, str | int] | None] = mapped_column(JSON, nullable=True)
    """The portion of the Butler "required data ID" (metadata primary keys)
    that is not already captured in instrument/visit, above.

    This is currently unused by this service, but will make it easier to
    migrate in the future if it turns out that more dimensions require special
    handling, similar to the ones we capture as proper columns already.
    """

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

    unembargo_time: Mapped[datetime | None] = mapped_column(types.DateTime(timezone=True), nullable=True)
    """Time when the dataset was copied out of embargo into the prompt_prep
    Butler repository.
    """

    __table_args__ = (
        ForeignKeyConstraint(["visit", "instrument"], ["visit.id", "visit.instrument"]),
        # For queries trying to determine which datasets need to be transferred
        # from one repository or another, we always have equality constraints
        # on dataset_type (because rules are defined on a
        # per-dataset-type basis) and prompt_prep_status (because
        # prompt_prep is the 'central' repository which is always involved in
        # transfers.)
        #
        # We have an index for each repository status, to make sure these
        # searches stay fast as the DB grows.  This might be overkill, but I'm
        # not sure at this point what the right tradeoff is between disk space
        # vs consistency/reliability of Postgres' query planning, so I'm
        # leaning towards the latter.
        *(
            Index(f"dataset_{column}_lookup", column, "prompt_prep_status", "dataset_type")
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


class PublishableDataset(Base):
    """Table tracking which datasets are candidates for publication for each
    day_obs.
    """

    __tablename__ = "publishable_dataset"

    day_obs: Mapped[int] = mapped_column(types.BigInteger, ForeignKey("day_obs.id"), primary_key=True)
    """Observation date as the day_obs dimension value from the Butler."""
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("dataset.id"), primary_key=True)
    """Butler Dataset UUID."""


class UnknownDataset(Base):
    """Table storing a list of datasets that we were instructed to register in
    the database, but which were not available in the original repository when
    we attempted to look them up.
    """

    __tablename__ = "unknown_dataset"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    """Butler Dataset UUID."""
    error: Mapped[str]
    """Human readable string describing why this dataset is being tracked in
    this table.
    """


for table in (Dataset, Visit):
    for status_column in _butler_repository_to_status_column.values():
        if getattr(table, status_column, None) is None:
            raise AssertionError(f"Table {table.__tablename__} is missing status column {status_column}")
