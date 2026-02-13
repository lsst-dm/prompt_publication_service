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

__all__ = ("repo_main_transfer_task",)

from uuid import UUID

from ..config import DatasetTypeConfiguration
from ..database import Database
from .impl.transfer_exec import transfer_in_worker_pool
from .impl.transfer_task import (
    MAX_DATASETS_PER_QUERY,
    TransferConfig,
    TransferTask,
    create_transfer_lookup_query,
)


async def _find_datasets_to_copy_to_repo_main(config: DatasetTypeConfiguration, db: Database) -> list[UUID]:
    async with db.session() as session:
        query = create_transfer_lookup_query("prompt_prep", "/repo/main").limit(MAX_DATASETS_PER_QUERY)
        async with db.session() as session:
            dataset_ids = await session.scalars(query)
            return list(dataset_ids)


repo_main_transfer_task = TransferTask(
    TransferConfig(
        source_repository="prompt_prep",
        target_repository="/repo/main",
        transfer_mode="unsafe_direct",
        dataset_lookup_function=_find_datasets_to_copy_to_repo_main,
        dataset_transfer_function=transfer_in_worker_pool,
        batch_size=20000,
        max_concurrency=2,
        target_time_column=None,
    )
)
