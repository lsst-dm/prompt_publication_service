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
from itertools import batched
from uuid import UUID

from sqlalchemy import Select, union_all

from lsst.daf.butler import DatasetId
from lsst.daf.butler._rubin.transfer_datasets_in_place import transfer_datasets_in_place

from ..logging import get_global_logger
from ..schema import ButlerRepository, Dataset
from .base import Task, TaskContext, TaskRunResult
from .impl.dataset_transfer_tracker import DatasetTransferTracker
from .impl.transfer_task import (
    MAX_DATASETS_PER_QUERY,
    create_transfer_lookup_query,
)

_LOG = get_global_logger()

OUTPUT_TAGGED_COLLECTION = "Prompt/Available/Outputs"


class PublishTask(Task):
    _BATCH_SIZE = 10000
    _MAX_CONCURRENCY = 16

    def __init__(self, *, source_repository: ButlerRepository, target_repository: ButlerRepository) -> None:
        self._source_repository = source_repository
        self._target_repository = target_repository
        self._log = _LOG.bind(
            task="publish visits",
            source_repository=source_repository,
            target_repository=target_repository,
        )
        self._concurrency_semaphore = asyncio.BoundedSemaphore(self._MAX_CONCURRENCY)

    async def run(self, ctx: TaskContext) -> TaskRunResult[list[DatasetId]]:
        datasets = await self._find_datasets_to_publish(ctx)
        self._log.info("datasets found", count=len(datasets))
        if len(datasets) == 0:
            return TaskRunResult("no-work-found", data=[])

        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(self._publish_datasets(ctx, batch))
                for batch in batched(datasets, self._BATCH_SIZE)
            ]
        successful_datasets: list[DatasetId] = []
        for task in tasks:
            successful_datasets.extend(task.result())
        return TaskRunResult("success", data=successful_datasets)

    async def _find_datasets_to_publish(self, ctx: TaskContext) -> list[DatasetId]:
        queries: list[Select[UUID]] = []
        for group in ctx.dataset_config.filter(lambda c: c.publish_to_public).group_by_origin():
            query = create_transfer_lookup_query("prompt_prep", "prompt_google_int").where(
                Dataset.origin == group.origin,
                Dataset.dataset_type.in_(group.dataset_types),
            )
            queries.append(query)

        async with ctx.state_database.session() as session:
            combined_query = union_all(*queries).limit(MAX_DATASETS_PER_QUERY)
            dataset_ids = await session.scalars(combined_query)
        return list(dataset_ids)

    async def _publish_datasets(self, ctx: TaskContext, datasets: tuple[DatasetId, ...]) -> set[DatasetId]:
        async with self._concurrency_semaphore:

            def publish() -> DatasetTransferTracker:
                with (
                    ctx.butler_factory.create_butler(self._source_repository) as source_butler,
                    ctx.butler_factory.create_butler(self._target_repository) as target_butler,
                ):
                    tracker = DatasetTransferTracker(
                        source_repository=self._source_repository, target_repository=self._target_repository
                    )
                    found_refs = tracker.find_datasets(source_butler, datasets)
                    transfer_datasets_in_place(source_butler, target_butler, found_refs)
                    target_butler.registry.associate(OUTPUT_TAGGED_COLLECTION, found_refs)
                    tracker.mark_refs_completed(found_refs)
                    return tracker

        result = await asyncio.to_thread(publish)
        async with ctx.state_database.session() as session:
            await result.persist_transfer_result(session)
            await session.commit()

        return result.get_complete_datasets()


publish_to_google_task = PublishTask(
    source_repository="prompt_prep",
    target_repository="prompt_google_int",
)
