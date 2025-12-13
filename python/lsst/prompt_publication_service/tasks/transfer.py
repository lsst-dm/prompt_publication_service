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

from datetime import datetime, timezone, timedelta
from uuid import UUID
from sqlalchemy import select, union_all, Select

from ..config import DatasetTypeConfiguration
from ..database import Database
from ..schema import Dataset, Visit, DatasetLocationStatus


async def find_datasets_to_unembargo(config: DatasetTypeConfiguration, db: Database) -> list[UUID]:
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
