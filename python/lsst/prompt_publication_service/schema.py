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
from typing import Any
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
    pass


class Visit(Base):
    __tablename__ = "visit"
    visit: Mapped[int] = mapped_column(types.BigInteger, primary_key=True)
    instrument: Mapped[str] = mapped_column(primary_key=True)
    time: Mapped[datetime | None]


class Dataset(Base):
    __tablename__ = "dataset"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    origin: Mapped[DatasetOrigin] = mapped_column(_EnumColumn(DatasetOrigin))
    dataset_type: Mapped[str]
    instrument: Mapped[str] = mapped_column(nullable=True)
    visit: Mapped[int] = mapped_column(types.BigInteger, nullable=True)

    embargo_status: Mapped[DatasetLocationStatus] = mapped_column(_EnumColumn(DatasetLocationStatus))
    prompt_prep_status: Mapped[DatasetLocationStatus] = mapped_column(
        _EnumColumn(DatasetLocationStatus), default=DatasetLocationStatus.NEVER_PRESENT
    )
    repo_main_status: Mapped[DatasetLocationStatus] = mapped_column(
        _EnumColumn(DatasetLocationStatus), default=DatasetLocationStatus.NEVER_PRESENT
    )
    google_int_status: Mapped[DatasetLocationStatus] = mapped_column(
        _EnumColumn(DatasetLocationStatus), default=DatasetLocationStatus.NEVER_PRESENT
    )
    google_prod_status: Mapped[DatasetLocationStatus] = mapped_column(
        _EnumColumn(DatasetLocationStatus), default=DatasetLocationStatus.NEVER_PRESENT
    )

    unembargo_time: Mapped[datetime | None]

    __table_args__ = (
        ForeignKeyConstraint(["visit", "instrument"], ["visit.visit", "visit.instrument"]),
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


class UnknownDataset(Base):
    """Stores a list of datasets that we were instructed to register in the
    database, but which were not available in the original repository when we
    attempted to look them up.
    """

    __tablename__ = "unknown_dataset"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    origin: Mapped[DatasetOrigin] = mapped_column(_EnumColumn(DatasetOrigin))
    error: Mapped[str]
