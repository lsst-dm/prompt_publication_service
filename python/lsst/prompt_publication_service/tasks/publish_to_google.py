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
from uuid import UUID

from sqlalchemy import Select, union_all

from lsst.daf.butler import DatasetId
from lsst.daf.butler._rubin.transfer_datasets_in_place import transfer_datasets_in_place

from ..config import DatasetTypeConfiguration
from ..database import Database
from ..schema import Dataset
from .base import TaskContext
from .impl.transfer_exec import lookup_datasets
from .impl.transfer_task import (
    MAX_DATASETS_PER_QUERY,
    DatasetTransferResult,
    TransferConfig,
    TransferTask,
    create_transfer_lookup_query,
)

OUTPUT_TAGGED_COLLECTION = "Prompt/Available/Outputs"


async def _find_datasets_to_publish(config: DatasetTypeConfiguration, db: Database) -> list[UUID]:
    queries: list[Select[tuple[UUID]]] = []
    for group in config.filter(lambda c: c.publish_to_public).group_by_origin():
        query = create_transfer_lookup_query("prompt_prep", "prompt_google_int").where(
            Dataset.origin == group.origin,
            Dataset.dataset_type.in_(group.dataset_types),
        )
        queries.append(query)

    async with db.session() as session:
        combined_query = union_all(*queries).limit(MAX_DATASETS_PER_QUERY)
        dataset_ids = await session.scalars(combined_query)
    return list(dataset_ids)


async def _publish_datasets(
    ctx: TaskContext, config: TransferConfig, datasets: tuple[DatasetId, ...]
) -> DatasetTransferResult:
    def publish() -> DatasetTransferResult:
        with (
            ctx.butler_factory.create_butler(config.source_repository) as source_butler,
            ctx.butler_factory.create_butler(config.target_repository) as target_butler,
        ):
            lookup = lookup_datasets(source_butler, datasets)
            transfer_datasets_in_place(source_butler, target_butler, lookup.found_refs)
            target_butler.registry.associate(OUTPUT_TAGGED_COLLECTION, lookup.found_refs)
            return DatasetTransferResult(
                missing_datasets=list(lookup.missing_ids), transferred_datasets=list(lookup.found_ids)
            )

    return await asyncio.to_thread(publish)


publish_to_google_task = TransferTask(
    TransferConfig(
        source_repository="prompt_prep",
        target_repository="prompt_google_int",
        dataset_lookup_function=_find_datasets_to_publish,
        dataset_transfer_function=_publish_datasets,
        batch_size=10000,
        max_concurrency=16,
        target_time_column=None,
    )
)
