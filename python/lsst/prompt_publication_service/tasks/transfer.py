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
import logging
from collections.abc import Iterable
from datetime import datetime, timezone, timedelta
from itertools import batched
from typing import NamedTuple

from uuid import UUID
from sqlalchemy import select, union_all, Select, update

from lsst.daf.butler import Butler

from ..config import DatasetTypeConfiguration
from ..database import Database
from ..schema import Dataset, Visit, DatasetLocationStatus

_LOG = logging.getLogger(__name__)


async def unembargo_datasets(
    config: DatasetTypeConfiguration, source_butler: Butler, target_butler: Butler, db: Database
) -> None:
    datasets = await _find_datasets_to_unembargo(config, db)
    for batch in batched(datasets, 1000):
        result = await asyncio.to_thread(_transfer_datasets, source_butler, target_butler, batch)
        await _record_transfer_result(db, result, "embargo_status", "prompt_prep_status", "unembargo_time")


async def _find_datasets_to_unembargo(config: DatasetTypeConfiguration, db: Database) -> list[UUID]:
    MAX_DATASETS = 1_000_000

    queries: list[Select[tuple[UUID]]] = []
    for group in config.group_by(lambda c: c.embargo_period_hours):
        query = select(Dataset.id).where(
            Dataset.dataset_type.in_(group.dataset_types),
            Dataset.embargo_status == DatasetLocationStatus.PRESENT,
            Dataset.prompt_prep_status == DatasetLocationStatus.NEVER_PRESENT,
        )
        embargo_hours = group.key
        if embargo_hours > 0:
            unembargo_time = datetime.now(timezone.utc) - timedelta(hours=embargo_hours)
            query = query.join(Visit).where(Visit.time < unembargo_time)
        queries.append(query)

    async with db.session() as session:
        combined_query = union_all(*queries).limit(MAX_DATASETS)
        dataset_ids = await session.scalars(combined_query)
    return list(dataset_ids)


class _DatasetTransferResult(NamedTuple):
    missing_datasets: list[UUID]
    """Datasets that were not found in the source repository."""
    transferred_datasets: list[UUID]
    """Datasets that were successfully transferred to the target repository."""


def _transfer_datasets(
    source_butler: Butler, target_butler: Butler, dataset_ids: Iterable[UUID]
) -> _DatasetTransferResult:
    dataset_ids = frozenset(dataset_ids)
    datasets = source_butler.get_many_datasets(dataset_ids)
    found_ids = frozenset(ref.id for ref in datasets)
    # Dataset IDs that are not known to the Butler at all.
    missing_ids = dataset_ids - found_ids
    _LOG.warning(f"Datasets were not found in Butler registry: {missing_ids}")

    completed_refs = target_butler.transfer_from(source_butler, datasets, "copy", register_dataset_types=True)
    completed_ids = frozenset(ref.id for ref in completed_refs)

    # Dataset IDs that are known to the Butler "registry", but for which there
    # are no corresponding file records in the Butler "datastore".
    missing_datastore_entries = found_ids - completed_ids
    _LOG.warning(f"Datasets were not found in Butler datastore: {missing_datastore_entries}")

    return _DatasetTransferResult(
        missing_datasets=list(missing_ids.union(missing_datastore_entries)),
        transferred_datasets=list(completed_ids),
    )


async def _record_transfer_result(
    db: Database,
    transfer_result: _DatasetTransferResult,
    source_status_column: str,
    target_status_column: str,
    target_time_column: str,
) -> None:
    transfer_time = datetime.now(timezone.utc)

    async with db.session() as session:
        await session.execute(
            update(Dataset),
            [
                {"id": id, source_status_column: DatasetLocationStatus.MISSING}
                for id in transfer_result.missing_datasets
            ],
        )
        await session.execute(
            update(Dataset),
            [
                {
                    "id": id,
                    target_status_column: DatasetLocationStatus.PRESENT,
                    target_time_column: transfer_time,
                }
                for id in transfer_result.transferred_datasets
            ],
        )
        await session.commit()
