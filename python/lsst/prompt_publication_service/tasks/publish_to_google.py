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

import backoff
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from lsst.daf.butler import DataCoordinate, DatasetId
from lsst.daf.butler._rubin.transfer_datasets_in_place import transfer_datasets_in_place

from ..logging import get_global_logger
from ..schema import ButlerRepository, Dataset, DatasetLocationStatus, Visit, VisitPublicationStatus
from .base import Task, TaskContext, TaskRunResult
from .impl.dataset_transfer_tracker import DatasetTransferTracker

_LOG = get_global_logger()

OUTPUT_TAGGED_COLLECTION = "Prompt/Available/Outputs"


class PublishTask(Task):
    _MAX_CONCURRENCY = 16
    _MAX_VISITS_PER_QUERY = 1000

    def __init__(self, *, source_repository: ButlerRepository, target_repository: ButlerRepository) -> None:
        self._source_repository = source_repository
        self._target_repository = target_repository
        self._log = _LOG.bind(
            task="publish visits",
            source_repository=source_repository,
            target_repository=target_repository,
        )
        self._concurrency_semaphore = asyncio.BoundedSemaphore(self._MAX_CONCURRENCY)

    async def run(self, ctx: TaskContext) -> TaskRunResult[list[int]]:
        visits = await self._find_visits_to_publish(ctx)
        self._log.info("visits found", count=len(visits))
        if len(visits) == 0:
            return TaskRunResult("no-work-found", data=[])

        async with asyncio.TaskGroup() as tg:
            for visit in visits:
                tg.create_task(self._publish_visit(ctx, visit))
        return TaskRunResult("success", data=[visit.id for visit in visits])

    async def _find_visits_to_publish(self, ctx: TaskContext) -> list[Visit]:
        """Finds the visits are ready to be published to Google."""
        async with self._concurrency_semaphore:
            published_dataset_types = ctx.dataset_config.filter(
                lambda item: item.publish_to_public
            ).dataset_types()

            query = (
                select(Visit)
                .where(
                    Visit.get_publication_status_column(self._source_repository)
                    == VisitPublicationStatus.NEVER_PRESENT,
                    # Only publish visits for which all publishable datasets have been
                    # successfully unembargoed.
                    select(Dataset.prompt_prep_status == DatasetLocationStatus.PRESENT)
                    .where(Dataset.visit == Visit.id, Dataset.dataset_type.in_(published_dataset_types))
                    .scalar_subquery()
                    .all_(),
                )
                .limit(self._MAX_VISITS_PER_QUERY)
            )
            async with ctx.state_database.session() as session:
                return list(await session.scalars(query))

    async def _publish_visit(self, ctx: TaskContext, visit: Visit) -> None:
        datasets = await self._find_datasets_to_publish(ctx, visit)
        try:
            dataset_result = await asyncio.to_thread(self._publish_visit_sync, ctx, visit, datasets)

            await dataset_result.persist_transfer_result()
            # run publish_visit_sync
            # do state update
        except _IncompleteVisitError:
            pass
            # mark visit missing

    @backoff.on_exception(backoff.expo, OperationalError, max_tries=5, max_time=60)
    def _publish_visit_sync(
        self, ctx: TaskContext, visit: Visit, datasets: list[DatasetId]
    ) -> DatasetTransferTracker:
        with (
            ctx.butler_factory.create_butler(self._source_repository) as source_butler,
            ctx.butler_factory.create_butler(self._target_repository) as target_butler,
        ):
            # Confirm that all
            tracker = DatasetTransferTracker(
                source_repository=self._source_repository, target_repository=self._target_repository
            )
            found_refs = tracker.find_datasets(source_butler, datasets)
            if tracker.get_missing_datasets():
                self._log.error(
                    "Visit publication failed due to missing datasets",
                    visit=visit.id,
                    missing_datasets=tracker.get_missing_datasets(),
                )
                raise _IncompleteVisitError()

            # Publish visit and visit-associated dimension records.
            data_coordinate = DataCoordinate.standardize(
                {"instrument": visit.instrument, "visit": visit.id},
                universe=source_butler.dimensions,
            )
            target_butler.transfer_dimension_records_from(source_butler, [data_coordinate])

            # Transfer the datasets associated with the visit.
            transfer_datasets_in_place(source_butler, target_butler, found_refs)
            target_butler.registry.associate(OUTPUT_TAGGED_COLLECTION, found_refs)
            tracker.mark_refs_completed(found_refs)
            return tracker

    async def _find_datasets_to_publish(self, ctx: TaskContext, visit: Visit) -> list[DatasetId]:
        dataset_types = ctx.dataset_config.filter(lambda c: c.publish_to_public).dataset_types()
        query = select(Dataset.id).where(
            Dataset.visit == visit.id and Dataset.instrument == visit.instrument,
            Dataset.dataset_type.in_(dataset_types),
            Dataset.get_status_column(self._source_repository) == DatasetLocationStatus.PRESENT,
        )
        async with ctx.state_database.session() as session:
            return list(await session.scalars(query))

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


class _IncompleteVisitError(Exception):
    """Raised when a visit cannot be published because data is missing."""


publish_to_google_task = PublishTask(
    source_repository="prompt_prep",
    target_repository="prompt_google_int",
)
