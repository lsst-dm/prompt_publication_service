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

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from itertools import batched
from uuid import UUID

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lsst.daf.butler import Butler, DatasetId, DatasetRef

from ...config import DatasetTypeConfiguration
from ...database import Database
from ...date_time_source import DateTimeSource
from ...logging import get_global_logger
from ...schema import (
    ButlerRepository,
    Dataset,
    DatasetLocationStatus,
    DimensionRecordStatus,
    Visit,
)
from ..base import Task, TaskContext, TaskRunResult

_LOG = get_global_logger()


@dataclass(frozen=True)
class TransferConfig:
    source_repository: ButlerRepository
    """Label of the Butler repository that datasets will be transferred
    from.
    """
    target_repository: ButlerRepository
    """Label of the Butler repository that datasets will be transferred to."""
    dataset_lookup_function: Callable[[DatasetTypeConfiguration, Database], Awaitable[list[DatasetId]]]
    """Function that will be called to find the UUIDs of the datasets that
    will be transferred.
    """
    dataset_transfer_function: Callable[
        [TaskContext, TransferConfig, tuple[DatasetId, ...]], Awaitable[DatasetTransferTracker]
    ]
    """Function called to execute the actual transfer of datasets."""
    batch_size: int
    """Maximum number of datasets to transfer in a single batch."""
    max_concurrency: int
    """Maximum number of processes to execute in parallel to run this task."""
    target_time_column: str | None
    """Column name in the Dataset table containing the time associated with
    this transfer.  If not `None, this will be set to the current time when a
    dataset is transferred successfully.
    """


class TransferTask(Task):
    def __init__(self, transfer_config: TransferConfig):
        self._config = transfer_config
        self._log = _LOG.bind(
            task="dataset transfer",
            source_repository=transfer_config.source_repository,
            target_repository=transfer_config.target_repository,
        )
        # Limit maximum parallelism of batch processing.  Butler also
        # internally multithreads file transfers, so this is the maximum
        # parallelism of Butler database operations but the number of
        # concurrent file transfers is larger.
        self._concurrency_semaphore = asyncio.BoundedSemaphore(self._config.max_concurrency)

    async def run(self, ctx: TaskContext) -> TaskRunResult[list[DatasetId]]:
        datasets = await self._config.dataset_lookup_function(ctx.dataset_config, ctx.state_database)
        self._log.info("datasets found", count=len(datasets))
        if len(datasets) == 0:
            return TaskRunResult("no-work-found", data=[])

        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(self._process_batch(ctx, batch))
                for batch in batched(datasets, self._config.batch_size)
            ]
        successful_datasets: list[DatasetId] = []
        for task in tasks:
            successful_datasets.extend(task.result())
        return TaskRunResult("success", data=successful_datasets)

    async def _process_batch(self, ctx: TaskContext, batch: tuple[DatasetId, ...]) -> set[DatasetId]:
        async with self._concurrency_semaphore:
            self._log.info("starting butler transfer", count=len(batch))

            result = await self._config.dataset_transfer_function(ctx, self._config, batch)
            completed_ids = result.get_complete_datasets()
            self._log.info(
                "completed butler transfer",
                transferred=len(completed_ids),
                missing=len(result.get_missing_datasets()),
            )

            async with ctx.state_database.session() as session:
                await result.persist_transfer_result(session, self._config.target_time_column)
                await session.commit()
            self._log.info("completed state DB update")

            return completed_ids


class DatasetTransferTracker:
    def __init__(
        self,
        *,
        source_repository: ButlerRepository,
        target_repository: ButlerRepository,
    ) -> None:
        self._source_repository = source_repository
        self._target_repository = target_repository
        self._missing_ids: set[DatasetId] = set()
        self._found_ids: set[DatasetId] = set()
        self._completed_ids: set[DatasetId] = set()

    def find_datasets(self, source_butler: Butler, dataset_ids: Iterable[DatasetId]) -> list[DatasetRef]:
        dataset_ids = frozenset(dataset_ids)
        found_refs = source_butler.get_many_datasets(dataset_ids)
        found_ids = frozenset(ref.id for ref in found_refs)
        # Dataset IDs that are not known to the Butler at all
        # (missing from both "registry" and "datastore").
        missing_ids = frozenset(dataset_ids - found_ids)
        self._missing_ids.update(missing_ids)
        self._found_ids.update(found_ids)
        return found_refs

    def get_missing_datasets(self) -> set[DatasetId]:
        return set(self._missing_ids)

    def get_complete_datasets(self) -> set[DatasetId]:
        return set(self._completed_ids)

    def get_incomplete_datasets(self) -> set[DatasetId]:
        return self._found_ids - self._completed_ids

    def mark_datasets_completed(self, dataset_ids: Iterable[DatasetId]) -> None:
        self._completed_ids.update(dataset_ids)

    def mark_refs_completed(self, refs: Iterable[DatasetRef]) -> None:
        self._completed_ids.update(ref.id for ref in refs)

    def mark_incomplete_as_missing(self) -> None:
        self._missing_ids.update(self.get_incomplete_datasets())

    async def persist_transfer_result(
        self,
        session: AsyncSession,
        target_time_column: str | None = None,
    ) -> None:
        transfer_time = DateTimeSource.now()
        source_status_column = Dataset.get_status_column_name(self._source_repository)
        target_status_column = Dataset.get_status_column_name(self._target_repository)

        await session.execute(
            update(Dataset),
            [
                {
                    "id": id,
                    source_status_column: DatasetLocationStatus.MISSING,
                }
                for id in self._missing_ids
            ],
        )

        if target_time_column is None:
            time_update = {}
        else:
            time_update = {target_time_column: transfer_time}
        await session.execute(
            update(Dataset),
            [
                {
                    "id": id,
                    target_status_column: DatasetLocationStatus.PRESENT,
                    **time_update,
                }
                for id in self._completed_ids
            ],
        )


MAX_DATASETS_PER_QUERY = 1_000_000


def create_transfer_lookup_query(
    source_repository: ButlerRepository, target_repository: ButlerRepository
) -> Select[UUID]:
    """Returns a SQL query against the Dataset table that finds the dataset
    UUID of candidates that can be copied from the given source repository to
    the target.  The Visit table is joined to the resulting query against the
    Dataset table.
    """
    return (
        select(Dataset.id)
        .join(Visit, isouter=True)
        .where(
            Dataset.get_status_column(source_repository) == DatasetLocationStatus.PRESENT,
            Dataset.get_status_column(target_repository) == DatasetLocationStatus.NEVER_PRESENT,
            # Make sure any visit, exposure or group records needed by the dataset
            # have already been loaded into the target repository.
            Visit.get_status_column(target_repository) != DimensionRecordStatus.NEVER_PRESENT,
        )
    )
