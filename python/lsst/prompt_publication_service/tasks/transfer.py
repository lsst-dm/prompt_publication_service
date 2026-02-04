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

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from itertools import batched
from typing import Literal, Callable, Awaitable

from uuid import UUID
from sqlalchemy import select, union_all, Select, update

from lsst.daf.butler import DatasetId, LabeledButlerFactory

from ..config import DatasetTypeConfiguration
from ..database import Database
from ..schema import Dataset, Visit, DatasetLocationStatus
from ..date_time_source import DateTimeSource

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransferConfig:
    source_repository: str
    """Label of the Butler repository that datasets will be transferred
    from.
    """
    target_repository: str
    """Label of the Butler repository that datasets will be transferred to."""
    transfer_mode: Literal["copy", "hardlink"]
    """Butler transfer mode, see `lsst.daf.butler.Butler.transfer_from`."""
    dataset_lookup_function: Callable[[DatasetTypeConfiguration, Database], Awaitable[list[DatasetId]]]
    """Function that will be called to find the UUIDs of the datasets that
    will be transferred.
    """
    batch_size: int
    """Maximum number of datasets to transfer in a single batch."""
    source_status_column: str
    """Column name in the Dataset table containing the location status for the
    source repository.  This status will be updated to
    `DatasetLocationStatus.MISSING` if a dataset is not found in the source
    repository.
    """
    target_status_column: str
    """Column name in the Dataset table containing the location status for the
    target repository.  This status will be updated to
    `DatasetLocationStatus.PRESENT` when a dataset is transferred successfully.
    """
    target_time_column: str | None
    """Column name in the Dataset table containing the time associated with
    this transfer.  If not `None, this will be set to the current time when a
    dataset is transferred successfully.
    """


@dataclass(frozen=True)
class _DatasetTransferResult:
    missing_datasets: list[UUID]
    """Datasets that were not found in the source repository."""
    transferred_datasets: list[UUID]
    """Datasets that were successfully transferred to the target repository."""


class TransferTask:
    def __init__(self, transfer_config: TransferConfig):
        self._config = transfer_config

    async def run(
        self, dataset_config: DatasetTypeConfiguration, butler_factory: LabeledButlerFactory, db: Database
    ) -> list[DatasetId]:
        datasets = await self._config.dataset_lookup_function(dataset_config, db)
        successful_datasets: list[DatasetId] = []
        for batch in batched(datasets, self._config.batch_size):
            result = await asyncio.to_thread(self._transfer_datasets, butler_factory, batch)
            await self._record_transfer_result(db, result)
            successful_datasets.extend(result.transferred_datasets)
        return successful_datasets

    def _transfer_datasets(
        self, butler_factory: LabeledButlerFactory, dataset_ids: Iterable[UUID]
    ) -> _DatasetTransferResult:
        dataset_ids = frozenset(dataset_ids)
        with (
            butler_factory.create_butler(label=self._config.source_repository) as source_butler,
            butler_factory.create_butler(label=self._config.target_repository) as target_butler,
        ):
            datasets = source_butler.get_many_datasets(dataset_ids)
            found_ids = frozenset(ref.id for ref in datasets)
            # Dataset IDs that are not known to the Butler at all.
            missing_ids = dataset_ids - found_ids
            if missing_ids:
                _LOG.warning(f"Datasets were not found in Butler registry: {missing_ids}")

            completed_refs = target_butler.transfer_from(
                source_butler, datasets, self._config.transfer_mode, register_dataset_types=True
            )
            completed_ids = frozenset(ref.id for ref in completed_refs)

            # Dataset IDs that are known to the Butler "registry", but for
            # which there are no corresponding file records in the Butler
            # "datastore".
            missing_datastore_entries = found_ids - completed_ids
            if missing_datastore_entries:
                _LOG.warning(f"Datasets were not found in Butler datastore: {missing_datastore_entries}")

            return _DatasetTransferResult(
                missing_datasets=list(missing_ids.union(missing_datastore_entries)),
                transferred_datasets=list(completed_ids),
            )

    async def _record_transfer_result(
        self,
        db: Database,
        transfer_result: _DatasetTransferResult,
    ) -> None:
        transfer_time = DateTimeSource.now()

        async with db.session() as session:
            await session.execute(
                update(Dataset),
                [
                    {"id": id, self._config.source_status_column: DatasetLocationStatus.MISSING}
                    for id in transfer_result.missing_datasets
                ],
            )

            if self._config.target_time_column is None:
                time_update = {}
            else:
                time_update = {self._config.target_time_column: transfer_time}
            await session.execute(
                update(Dataset),
                [
                    {
                        "id": id,
                        self._config.target_status_column: DatasetLocationStatus.PRESENT,
                        **time_update,
                    }
                    for id in transfer_result.transferred_datasets
                ],
            )
            await session.commit()


_MAX_DATASETS_PER_QUERY = 1_000_000


async def _find_datasets_to_unembargo(config: DatasetTypeConfiguration, db: Database) -> list[UUID]:
    queries: list[Select[tuple[UUID]]] = []
    for group in config.group_by(lambda c: c.embargo_period_hours):
        query = select(Dataset.id).where(
            Dataset.dataset_type.in_(group.dataset_types),
            Dataset.embargo_status == DatasetLocationStatus.PRESENT,
            Dataset.prompt_prep_status == DatasetLocationStatus.NEVER_PRESENT,
        )
        embargo_hours = group.key
        if embargo_hours > 0:
            unembargo_time = DateTimeSource.now() - timedelta(hours=embargo_hours)
            # Note: this will not find datasets that are tracked by `exposure`
            # instead of `visit`.  At the time of writing no exposure datasets
            # with embargo restrictions are planned for publication.  If that
            # changes, this will also need to test against the time from the
            # `Exposure` table.
            query = query.join(Visit).where(Visit.time < unembargo_time)
        queries.append(query)

    async with db.session() as session:
        combined_query = union_all(*queries).limit(_MAX_DATASETS_PER_QUERY)
        dataset_ids = await session.scalars(combined_query)
    return list(dataset_ids)


unembargo_transfer_task = TransferTask(
    TransferConfig(
        source_repository="embargo",
        target_repository="prompt_prep",
        transfer_mode="copy",
        dataset_lookup_function=_find_datasets_to_unembargo,
        # File copy can be slow and unreliable, and Butler currently holds DB
        # transactions open during the file transfer process.  So it's best to
        # copy only a handful of files at a time.
        batch_size=100,
        source_status_column="embargo_status",
        target_status_column="prompt_prep_status",
        target_time_column="unembargo_time",
    )
)


async def _find_datasets_to_copy_to_repo_main(config: DatasetTypeConfiguration, db: Database) -> list[UUID]:
    async with db.session() as session:
        query = (
            select(Dataset.id)
            .where(
                Dataset.prompt_prep_status == DatasetLocationStatus.PRESENT,
                Dataset.repo_main_status == DatasetLocationStatus.NEVER_PRESENT,
            )
            .limit(_MAX_DATASETS_PER_QUERY)
        )
        async with db.session() as session:
            dataset_ids = await session.scalars(query)
            return list(dataset_ids)


repo_main_transfer_task = TransferTask(
    TransferConfig(
        source_repository="prompt_prep",
        target_repository="/repo/main",
        transfer_mode="hardlink",
        dataset_lookup_function=_find_datasets_to_copy_to_repo_main,
        batch_size=10000,
        source_status_column="prompt_prep_status",
        target_status_column="repo_main_status",
        target_time_column=None,
    )
)
