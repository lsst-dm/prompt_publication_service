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
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from itertools import batched
from typing import Literal, Callable, Awaitable
from uuid import UUID

from sqlalchemy import select, union_all, Select, update

from lsst.daf.butler import DatasetId
from .process_pool import WorkerTaskContext

from ..config import DatasetTypeConfiguration
from ..database import Database
from ..schema import (
    Dataset,
    Group,
    Visit,
    Exposure,
    DatasetLocationStatus,
    ButlerRepository,
    DimensionRecordStatus,
)
from ..date_time_source import DateTimeSource
from .base import TaskContext, TaskRunResult, Task
from ..logging import get_global_logger

_LOG = get_global_logger()


@dataclass(frozen=True)
class TransferConfig:
    source_repository: ButlerRepository
    """Label of the Butler repository that datasets will be transferred
    from.
    """
    target_repository: ButlerRepository
    """Label of the Butler repository that datasets will be transferred to."""
    transfer_mode: Literal["copy", "unsafe_direct"]
    """Butler transfer mode, see `lsst.daf.butler.Butler.transfer_from`."""
    dataset_lookup_function: Callable[[DatasetTypeConfiguration, Database], Awaitable[list[DatasetId]]]
    """Function that will be called to find the UUIDs of the datasets that
    will be transferred.
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


@dataclass(frozen=True)
class _DatasetTransferResult:
    missing_datasets: list[UUID]
    """Datasets that were not found in the source repository."""
    transferred_datasets: list[UUID]
    """Datasets that were successfully transferred to the target repository."""


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

    async def _process_batch(self, ctx: TaskContext, batch: tuple[DatasetId, ...]) -> list[DatasetId]:
        async with self._concurrency_semaphore:
            self._log.info("starting butler transfer", count=len(batch))
            result = await ctx.worker_pool.run(
                _transfer_datasets,
                source_repository=self._config.source_repository,
                target_repository=self._config.target_repository,
                transfer_mode=self._config.transfer_mode,
                dataset_ids=batch,
            )
            self._log.info(
                "completed butler transfer",
                transferred=len(result.transferred_datasets),
                missing=len(result.missing_datasets),
            )
            await self._record_transfer_result(ctx.state_database, result)
            self._log.info("completed state DB update")
            return result.transferred_datasets

    async def _record_transfer_result(
        self,
        db: Database,
        transfer_result: _DatasetTransferResult,
    ) -> None:
        transfer_time = DateTimeSource.now()
        source_status_column = Dataset.get_status_column_name(self._config.source_repository)
        target_status_column = Dataset.get_status_column_name(self._config.target_repository)

        async with db.session() as session:
            await session.execute(
                update(Dataset),
                [
                    {
                        "id": id,
                        source_status_column: DatasetLocationStatus.MISSING,
                    }
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
                        target_status_column: DatasetLocationStatus.PRESENT,
                        **time_update,
                    }
                    for id in transfer_result.transferred_datasets
                ],
            )
            await session.commit()


def _transfer_datasets(
    context: WorkerTaskContext,
    source_repository: ButlerRepository,
    target_repository: ButlerRepository,
    transfer_mode: str,
    dataset_ids: Iterable[UUID],
) -> _DatasetTransferResult:
    """Transfer the given datasets from one Butler repository to another.  This
    function will be run in another process, via ProcessPoolExecutor.
    """
    dataset_ids = frozenset(dataset_ids)
    log = context.log.bind(
        task="dataset transfer",
        source_repository=source_repository,
        target_repository=target_repository,
    )
    with (
        context.butler_factory.create_butler(source_repository) as source_butler,
        context.butler_factory.create_butler(target_repository) as target_butler,
    ):
        datasets = source_butler.get_many_datasets(dataset_ids)
        found_ids = frozenset(ref.id for ref in datasets)
        # Dataset IDs that are not known to the Butler at all.
        missing_ids = dataset_ids - found_ids
        if missing_ids:
            log.warning("Datasets were not found in Butler registry", missing_ids=missing_ids)

        completed_refs = target_butler.transfer_from(
            source_butler, datasets, transfer_mode, register_dataset_types=True
        )
        completed_ids = frozenset(ref.id for ref in completed_refs)

        # Dataset IDs that are known to the Butler "registry", but for
        # which there are no corresponding file records in the Butler
        # "datastore".
        missing_datastore_entries = found_ids - completed_ids
        if missing_datastore_entries:
            log.warning(
                "Datasets were not found in Butler datastore",
                missing_datastore_entries=missing_datastore_entries,
            )

        return _DatasetTransferResult(
            missing_datasets=list(missing_ids.union(missing_datastore_entries)),
            transferred_datasets=list(completed_ids),
        )


_MAX_DATASETS_PER_QUERY = 1_000_000


def _create_transfer_lookup_query(
    source_repository: ButlerRepository, target_repository: ButlerRepository
) -> Select[tuple[UUID]]:
    """Returns a SQL query against the Dataset table that finds the dataset
    UUID of candidates that can be copied from the given source repository to
    the target.  The Visit, Exposure, and Group tables are joined to the
    resulting query against the Dataset table.
    """
    return (
        select(Dataset.id)
        .join(Visit, isouter=True)
        .join(Exposure, isouter=True)
        .join(Group, isouter=True)
        .where(
            Dataset.get_status_column(source_repository) == DatasetLocationStatus.PRESENT,
            Dataset.get_status_column(target_repository) == DatasetLocationStatus.NEVER_PRESENT,
            # Make sure any visit or exposure records needed by the dataset
            # have already been loaded into the target repository.
            Dataset.visit.is_(None)
            | (Visit.get_status_column(target_repository) != DimensionRecordStatus.NEVER_PRESENT),
            Dataset.exposure.is_(None)
            | (Exposure.get_status_column(target_repository) != DimensionRecordStatus.NEVER_PRESENT),
            Dataset.group.is_(None)
            | (Group.get_status_column(target_repository) != DimensionRecordStatus.NEVER_PRESENT),
        )
    )


async def _find_datasets_to_unembargo(config: DatasetTypeConfiguration, db: Database) -> list[UUID]:
    queries: list[Select[tuple[UUID]]] = []
    for group in config.group_by(lambda c: c.embargo_period_hours):
        query = _create_transfer_lookup_query("embargo", "prompt_prep").where(
            Dataset.origin == group.origin,
            Dataset.dataset_type.in_(group.dataset_types),
        )
        embargo_hours = group.key
        if embargo_hours > 0:
            unembargo_time = DateTimeSource.now() - timedelta(hours=embargo_hours)
            # Note: this will not find datasets that are tracked by `exposure`
            # instead of `visit`.  At the time of writing no exposure datasets
            # with embargo restrictions are planned for publication.  If that
            # changes, this will also need to test against the time from the
            # `Exposure` table.
            query = query.where(Visit.time < unembargo_time)
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
        max_concurrency=16,
        target_time_column="unembargo_time",
    )
)


async def _find_datasets_to_copy_to_repo_main(config: DatasetTypeConfiguration, db: Database) -> list[UUID]:
    async with db.session() as session:
        query = _create_transfer_lookup_query("prompt_prep", "/repo/main").limit(_MAX_DATASETS_PER_QUERY)
        async with db.session() as session:
            dataset_ids = await session.scalars(query)
            return list(dataset_ids)


repo_main_transfer_task = TransferTask(
    TransferConfig(
        source_repository="prompt_prep",
        target_repository="/repo/main",
        transfer_mode="unsafe_direct",
        dataset_lookup_function=_find_datasets_to_copy_to_repo_main,
        batch_size=20000,
        max_concurrency=2,
        target_time_column=None,
    )
)
