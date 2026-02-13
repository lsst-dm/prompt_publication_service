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

__all__ = ("unembargo_transfer_task",)

from datetime import timedelta
from uuid import UUID

from sqlalchemy import Select, union_all

from ..config import DatasetTypeConfiguration
from ..database import Database
from ..date_time_source import DateTimeSource
from ..schema import Dataset, Visit
from .impl.transfer import MAX_DATASETS_PER_QUERY, TransferConfig, TransferTask, create_transfer_lookup_query


async def _find_datasets_to_unembargo(config: DatasetTypeConfiguration, db: Database) -> list[UUID]:
    queries: list[Select[tuple[UUID]]] = []
    for group in config.group_by(lambda c: c.embargo_period_hours):
        query = create_transfer_lookup_query("embargo", "prompt_prep").where(
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
        combined_query = union_all(*queries).limit(MAX_DATASETS_PER_QUERY)
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
