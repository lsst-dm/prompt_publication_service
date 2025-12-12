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
from typing import cast
from uuid import UUID

import astropy.time
import logging
import pydantic

from lsst.daf.butler import Butler, DataCoordinate, DatasetRef, DimensionRecord, Timespan
from lsst.resources import ResourcePath

from .database import Database
from .schema import Dataset, Visit, DatasetOrigin, DatasetLocationStatus, UnknownDataset

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
            "included datasets not found in the Butler repository: {missing_ids}"
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

    visit_records = await _find_matching_visits(source_butler, datasets)
    visit_rows = [_convert_visit_record_to_visit_row(record) for record in visit_records]
    dataset_rows = [_convert_ref_to_dataset_row(ref, origin) for ref in datasets]
    async with db.session() as session:
        if visit_rows:
            await session.execute(db.insert_if_not_exists(Visit), visit_rows)
        if missing:
            unknown_rows = [{"id": id, "origin": origin, "error": error} for id, error in missing.items()]
            await session.execute(db.insert_if_not_exists(UnknownDataset), unknown_rows)
        if dataset_rows:
            await session.execute(db.insert_if_not_exists(Dataset), dataset_rows)
        await session.commit()


async def _find_matching_visits(source_butler: Butler, datasets: list[DatasetRef]) -> list[DimensionRecord]:
    """Look up the Butler 'visit' dimension records associated with the given
    datasets.
    """
    visits: set[DataCoordinate] = set()
    for ref in datasets:
        if "visit" in ref.datasetType.dimensions:
            visits.add(ref.dataId.subset(["visit"]))

    if visits:
        return await asyncio.to_thread(_get_visit_dimension_records, source_butler, visits)
    else:
        return []


def _get_visit_dimension_records(butler: Butler, data_ids: set[DataCoordinate]) -> list[DimensionRecord]:
    with butler.query() as query:
        return list(query.join_data_coordinates(data_ids).dimension_records("visit"))


def _convert_visit_record_to_visit_row(record: DimensionRecord) -> dict:
    timespan: Timespan | None = record.timespan
    if timespan is None or timespan.end is None or timespan.end == Timespan.EMPTY:
        time = None
    else:
        assert isinstance(timespan.end, astropy.time.Time)

        utc_time = cast(astropy.time.Time, timespan.end.utc)
        time = utc_time.to_datetime(datetime.UTC)

    return {"instrument": record.dataId["instrument"], "visit": record.dataId["visit"], "time": time}


def _convert_ref_to_dataset_row(ref: DatasetRef, origin: DatasetOrigin) -> dict:
    instrument = None
    visit = None
    if "instrument" in ref.datasetType.dimensions:
        instrument = ref.dataId["instrument"]
    if "visit" in ref.datasetType.dimensions:
        visit = ref.dataId["visit"]
    if "exposure" in ref.datasetType.dimensions:
        # TODO: Not sure yet how we want to track exposure time and "can see
        # sky" for these.
        # Prompt processing outputs do not have exposure dimensions, only
        # visit.
        raise NotImplementedError(
            f"Dataset type '{ref.datasetType.name}' with exposure dimensions cannot yet be imported."
        )

    return {
        "id": ref.id,
        "origin": origin,
        "dataset_type": ref.datasetType.name,
        "instrument": instrument,
        "visit": visit,
        "embargo_status": DatasetLocationStatus.PRESENT,
    }
