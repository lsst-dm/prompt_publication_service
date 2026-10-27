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

from sqlalchemy import Select, select

from lsst.daf.butler import DatasetId

from ...config import DatasetTypeConfiguration
from ...database import Database
from ...logging import get_global_logger
from ...schema import (
    ButlerRepository,
    Dataset,
    DatasetLocationStatus,
    DimensionRecordStatus,
    Visit,
)
from ..base import Task, TaskContext, TaskRunResult
from .dataset_transfer_tracker import DatasetTransferTracker
from .process_pool import WorkerTaskContext

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
    transfer_mode: str
    """Butler transfer mode used for transferring datasets.  See
    `lsst.daf.Butler.transfer_from`.
    """
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

            result = await ctx.worker_pool.run(
                _transfer_datasets,
                source_repository=self._config.source_repository,
                target_repository=self._config.target_repository,
                transfer_mode=self._config.transfer_mode,
                dataset_ids=batch,
            )

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


def _transfer_datasets(
    context: WorkerTaskContext,
    source_repository: ButlerRepository,
    target_repository: ButlerRepository,
    transfer_mode: str,
    dataset_ids: Iterable[UUID],
) -> DatasetTransferTracker:
    """Transfer the given datasets from one Butler repository to another.  This
    function will be run in another process, via ProcessPoolExecutor.
    """
    log = context.log.bind(
        task="dataset transfer",
        source_repository=source_repository,
        target_repository=target_repository,
    )
    with (
        context.butler_factory.create_butler(source_repository) as source_butler,
        context.butler_factory.create_butler(target_repository) as target_butler,
    ):
        transfer_tracker = DatasetTransferTracker(
            source_repository=source_repository, target_repository=target_repository
        )
        found_refs = transfer_tracker.find_datasets(source_butler, dataset_ids)
        missing_ids = transfer_tracker.get_missing_datasets()
        if missing_ids:
            log.warning("Datasets were not found in Butler registry", missing_ids=missing_ids)

        completed_refs = target_butler.transfer_from(
            source_butler, found_refs, transfer_mode, register_dataset_types=True
        )
        transfer_tracker.mark_refs_completed(completed_refs)

        # If datasets passed into `transfer_from` were not returned from its
        # result set, that means the datasets were known to the Butler
        # "registry", but there are no corresponding file records in the Butler
        # "datastore".
        missing_datastore_entries = transfer_tracker.get_incomplete_datasets()
        if missing_datastore_entries:
            transfer_tracker.mark_incomplete_as_missing()
            log.warning(
                "Datasets were not found in Butler datastore",
                missing_datastore_entries=missing_datastore_entries,
            )

        return transfer_tracker


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
