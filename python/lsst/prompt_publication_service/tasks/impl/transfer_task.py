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
from dataclasses import dataclass
from itertools import batched
from typing import Awaitable, Callable
from uuid import UUID

from sqlalchemy import Select, select, update

from lsst.daf.butler import DatasetId

from ...config import DatasetTypeConfiguration
from ...database import Database
from ...date_time_source import DateTimeSource
from ...logging import get_global_logger
from ...schema import (
    ButlerRepository,
    Dataset,
    DatasetLocationStatus,
    DimensionRecordStatus,
    Exposure,
    Group,
    Visit,
)
from ..base import Task, TaskContext, TaskRunResult

_LOG = get_global_logger()


@dataclass(frozen=True)
class DatasetTransferResult:
    missing_datasets: list[UUID]
    """Datasets that were not found in the source repository."""
    transferred_datasets: list[UUID]
    """Datasets that were successfully transferred to the target repository."""


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
        [TaskContext, TransferConfig, tuple[DatasetId, ...]], Awaitable[DatasetTransferResult]
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

    async def _process_batch(self, ctx: TaskContext, batch: tuple[DatasetId, ...]) -> list[DatasetId]:
        async with self._concurrency_semaphore:
            self._log.info("starting butler transfer", count=len(batch))
            result = await self._config.dataset_transfer_function(ctx, self._config, batch)
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
        transfer_result: DatasetTransferResult,
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


MAX_DATASETS_PER_QUERY = 1_000_000


def create_transfer_lookup_query(
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
