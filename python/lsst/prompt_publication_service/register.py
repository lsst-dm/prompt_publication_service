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
import datetime
from uuid import UUID

import logging
import pydantic

from lsst.daf.butler import Butler, DataCoordinate, DatasetRef, DimensionRecord, Timespan
from lsst.resources import ResourcePath

from .database import Database
from .schema import Dataset, Visit, DatasetOrigin, DatasetLocationStatus, UnknownDataset, Exposure

_LOG = logging.getLogger(__name__)


class DatasetBatch(pydantic.BaseModel):
    """List of embargo datasets from Prompt Processing Butler Writer that
    should be registered in the database.
    """

    batch_id: UUID
    """Identifier for this batch of datasets."""
    datasets: list[UUID]
    """List of dataset IDs that were ingested into the Butler database."""


async def register_dataset_batch_file(
    db: Database, origin: DatasetOrigin, source_butler: Butler, batch_file: ResourcePath | str
) -> None:
    """Add a list of datasets to the state database from a dataset batch file.
    This function is idempotent and can safely be called on the same batch file
    more than once.  Datasets are assumed to be present in the embargo
    repository, but not any of the other repositories.

    Parameters
    ----------
    db
        Database connection to the state database.
    origin
        Enum value describing which system/process these datasets originated
        from.
    source_butler
        Butler instance for the repository the datasets are currently located
        (normally the 'embargo' repository.)
    batch_file
        Path to the JSON file containing the list of datasets to be loaded.
    """
    json = await asyncio.to_thread(lambda: ResourcePath(batch_file).read())
    batch = DatasetBatch.model_validate_json(json)
    refs = await asyncio.to_thread(source_butler.get_many_datasets, batch.datasets)
    missing = None
    missing_ids = set(batch.datasets) - set(ref.id for ref in refs)
    if missing_ids:
        _LOG.warning(
            f"Dataset batch {batch.batch_id}"
            f" included datasets not found in the Butler repository: {missing_ids}"
        )
        error_message = f"Dataset not found in Butler, from batch '{batch.batch_id}'"
        missing = {id: error_message for id in missing_ids}

    await register_embargo_datasets(db, origin, source_butler, refs, missing)


async def register_embargo_datasets(
    db: Database,
    origin: DatasetOrigin,
    source_butler: Butler,
    datasets: list[DatasetRef],
    missing: dict[UUID, str] | None = None,
) -> None:
    """Add a list of datasets to the state database.  This function is
    idempotent and can safely be called on the same datasets more than once.
    Datasets are assumed to be present in the embargo repository, but not any
    of the other repositories.

    Parameters
    ----------
    db
        Database connection to the state database.
    origin
        Enum value describing which system/process these datasets originated
        from.
    source_butler
        Butler instance for the repository the datasets are currently located
        (normally the 'embargo' repository.)
    datasets
        List of Butler `DatasetRef` instances for the datasets to be registered
        in the DB.
    missing, optional
        Mapping from dataset UUID to a human-readable string describing
        a dataset that you want to register, but could not be located.
        These dataset UUIDs will be tracked in the `UnknownDataset` table.
    """
    if len(datasets) == 0:
        return

    visit_records = await _find_matching_dimension_records(source_butler, "visit", datasets)
    visit_rows = [_convert_visit_record_to_visit_row(record) for record in visit_records]

    exposure_records = await _find_matching_dimension_records(source_butler, "exposure", datasets)
    exposure_rows = [_convert_exposure_record_to_exposure_row(record) for record in exposure_records]

    dataset_rows = [_convert_ref_to_dataset_row(ref, origin) for ref in datasets]
    async with db.session() as session:
        if visit_rows:
            await session.execute(db.insert_if_not_exists(Visit), visit_rows)
        if exposure_rows:
            await session.execute(db.insert_if_not_exists(Exposure), exposure_rows)
        if missing:
            unknown_rows = [{"id": id, "origin": origin, "error": error} for id, error in missing.items()]
            await session.execute(db.insert_if_not_exists(UnknownDataset), unknown_rows)
        if dataset_rows:
            await session.execute(db.insert_if_not_exists(Dataset), dataset_rows)
        await session.commit()


async def _find_matching_dimension_records(
    source_butler: Butler, dimension: str, datasets: list[DatasetRef]
) -> list[DimensionRecord]:
    """Look up the Butler dimension records for the given ``dimension``,
    associated with the given ``datasets``.
    """
    data_ids: set[DataCoordinate] = set()
    for ref in datasets:
        if dimension in ref.datasetType.dimensions:
            data_ids.add(ref.dataId.subset([dimension]))

    if data_ids:
        return await asyncio.to_thread(_get_dimension_records, source_butler, dimension, data_ids)
    else:
        return []


def _get_dimension_records(
    butler: Butler, dimension: str, data_ids: set[DataCoordinate]
) -> list[DimensionRecord]:
    with butler.query() as query:
        return list(query.join_data_coordinates(data_ids).dimension_records(dimension))


def _convert_butler_timespan_to_datetime(timespan: Timespan | None) -> datetime.datetime | None:
    if timespan is None or timespan.end is None or timespan.end is Timespan.EMPTY:
        return None
    else:
        utc_time = timespan.end.utc
        return utc_time.to_datetime(datetime.UTC)


def _convert_visit_record_to_visit_row(record: DimensionRecord) -> dict:
    return {
        "instrument": record.dataId["instrument"],
        "visit": record.dataId["visit"],
        "day_obs": record.get("day_obs"),
        "time": _convert_butler_timespan_to_datetime(record.timespan),
    }


def _convert_exposure_record_to_exposure_row(record: DimensionRecord) -> dict:
    # can_see_sky can be NULL in the Butler database.  NULL means "unknown
    # whether the sky was visible", so for purposes of unembargo we have to
    # assume yes.
    can_see_sky: bool | None = record.get("can_see_sky")
    if can_see_sky is None:
        can_see_sky = True

    return {
        "instrument": record.dataId["instrument"],
        "exposure": record.dataId["exposure"],
        "can_see_sky": can_see_sky,
        "day_obs": record.get("day_obs"),
        "time": _convert_butler_timespan_to_datetime(record.timespan),
    }


def _convert_ref_to_dataset_row(ref: DatasetRef, origin: DatasetOrigin) -> dict:
    return {
        "id": ref.id,
        "origin": origin,
        "dataset_type": ref.datasetType.name,
        "instrument": ref.dataId.get("instrument"),
        "visit": ref.dataId.get("visit"),
        "exposure": ref.dataId.get("exposure"),
        "embargo_status": DatasetLocationStatus.PRESENT,
    }
