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
from itertools import batched

import backoff
import sqlalchemy.exc
from sqlalchemy import select

from lsst.daf.butler import DataCoordinate, LabeledButlerFactory

from ..database import Database
from ..logging import get_global_logger
from ..schema import (
    ButlerRepository,
    DimensionRecordRow,
    DimensionRecordStatus,
    DimensionRecordTable,
)
from .base import Task, TaskContext, TaskRunResult

_LOG = get_global_logger()


class DimensionRecordCopyTask(Task):
    """Task for copying dimension records between Butler repositories."""

    def __init__(
        self,
        table: DimensionRecordTable,
        source_repository: ButlerRepository,
        target_repository: ButlerRepository,
    ) -> None:
        self._table = table
        self._source_repository = source_repository
        self._target_repository = target_repository
        self._log = _LOG.bind(
            task="dimension record copy",
            dimension=table.butler_dimension,
            source_repository=source_repository,
            target_repository=target_repository,
        )

    async def run(self, context: TaskContext) -> TaskRunResult[int]:
        rows = await self._find_records_to_unembargo(context.state_database)
        self._log.info("found rows", count=len(rows))
        if len(rows) == 0:
            return TaskRunResult("no-work-found", 0)

        batch_size = 5000
        for batch in batched(rows, batch_size):
            self._log.info("starting dimension record copy", count=len(batch))
            await asyncio.to_thread(self._transfer_dimension_records, context.butler_factory, batch)
            self._log.info("completed dimension record copy", count=len(batch))
            await self._record_result(context.state_database, batch)
            self._log.info("completed state DB update", count=len(batch))
        return TaskRunResult("success", len(rows))

    async def _find_records_to_unembargo(self, state_database: Database) -> list[DimensionRecordRow]:
        query = (
            select(self._table)
            .where(
                self._table.get_status_column(self._source_repository) == DimensionRecordStatus.INITIAL,
                self._table.get_status_column(self._target_repository) == DimensionRecordStatus.NEVER_PRESENT,
            )
            .limit(1_000_000)
        )
        async with state_database.session() as session:
            return list(await session.scalars(query))

    # Butler.transfer_dimension_records_from() is prone to database-level row
    # lock deadlocks.  Postgres will kill our query when deadlock occurs, and
    # we need to retry.
    @backoff.on_exception(backoff.expo, sqlalchemy.exc.OperationalError, max_tries=5, max_time=60)
    def _transfer_dimension_records(
        self, butler_factory: LabeledButlerFactory, rows: Iterable[DimensionRecordRow]
    ) -> None:
        with (
            butler_factory.create_butler(label=self._source_repository) as source_butler,
            butler_factory.create_butler(label=self._target_repository) as target_butler,
        ):
            data_coordinates = [
                DataCoordinate.standardize(
                    {"instrument": row.instrument, self._table.butler_dimension: row.id},
                    universe=source_butler.dimensions,
                )
                for row in rows
            ]
            target_butler.transfer_dimension_records_from(source_butler, data_coordinates)

    async def _record_result(self, state_database: Database, rows: Iterable[DimensionRecordRow]) -> None:
        async with state_database.session() as session:
            session.add_all(rows)
            for row in rows:
                row.set_status_column(self._target_repository, DimensionRecordStatus.INITIAL)
            await session.commit()
