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

from collections.abc import Iterable
from uuid import UUID

from lsst.daf.butler import DatasetId

from ...schema import ButlerRepository
from ..base import TaskContext
from .process_pool import WorkerTaskContext
from .transfer_task import DatasetTransferResult, TransferConfig


async def transfer_in_worker_pool(
    ctx: TaskContext, config: TransferConfig, datasets: tuple[DatasetId, ...]
) -> DatasetTransferResult:
    return await ctx.worker_pool.run(
        _transfer_datasets,
        source_repository=config.source_repository,
        target_repository=config.target_repository,
        transfer_mode=config.transfer_mode,
        dataset_ids=datasets,
    )


def _transfer_datasets(
    context: WorkerTaskContext,
    source_repository: ButlerRepository,
    target_repository: ButlerRepository,
    transfer_mode: str,
    dataset_ids: Iterable[UUID],
) -> DatasetTransferResult:
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

        return DatasetTransferResult(
            missing_datasets=list(missing_ids.union(missing_datastore_entries)),
            transferred_datasets=list(completed_ids),
        )
