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

from __future__ import annotations

import asyncio
import datetime
from collections.abc import Iterable
from uuid import UUID

import pydantic

from lsst.daf.butler import Butler, DataCoordinate, DatasetRef, DimensionRecord, Timespan
from lsst.resources import ResourcePath

from .database import Database
from .logging import get_global_logger
from .schema import Dataset, DatasetLocationStatus, DatasetOrigin, UnknownDataset, Visit

_LOG = get_global_logger()


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
    log = _LOG.bind(batch_file=str(batch_file))
    json = await asyncio.to_thread(lambda: ResourcePath(batch_file).read())
    batch = DatasetBatch.model_validate_json(json)
    refs = await asyncio.to_thread(source_butler.get_many_datasets, batch.datasets)
    missing = None
    missing_ids = set(batch.datasets) - set(ref.id for ref in refs)
    if missing_ids:
        log.warning(
            "Dataset batch included datasets not found in the Butler repository",
            batch_id=batch.batch_id,
            missing_ids=[str(id) for id in missing_ids],
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

    visit_mapper = await asyncio.to_thread(_VisitMapper, source_butler, datasets)
    visit_rows = [
        _convert_visit_record_to_visit_row(record) for record in visit_mapper.get_all_visit_records()
    ]
    dataset_rows = [_convert_ref_to_dataset_row(ref, origin, visit_mapper) for ref in datasets]
    async with db.session() as session:
        if visit_rows:
            await session.execute(db.insert_if_not_exists(Visit), visit_rows)
        if missing:
            unknown_rows = [{"id": id, "origin": origin, "error": error} for id, error in missing.items()]
            await session.execute(db.insert_if_not_exists(UnknownDataset), unknown_rows)
        if dataset_rows:
            await session.execute(db.insert_if_not_exists(Dataset), dataset_rows)
        await session.commit()


def _convert_butler_timespan_to_datetime(timespan: Timespan | None) -> datetime.datetime | None:
    if timespan is None or timespan.end is None or timespan.end is Timespan.EMPTY:
        return None
    else:
        utc_time = timespan.end.utc
        return utc_time.to_datetime(datetime.UTC)


def _convert_visit_record_to_visit_row(record: DimensionRecord) -> dict:
    return {
        "id": record.dataId["visit"],
        "instrument": record.dataId["instrument"],
        "day_obs": record.get("day_obs"),
        "time": _convert_butler_timespan_to_datetime(record.timespan),
    }


def _convert_ref_to_dataset_row(ref: DatasetRef, origin: DatasetOrigin, visit_mapper: _VisitMapper) -> dict:
    # Extract any leftover dimension primary keys that aren't already
    # represented as one of the columns in the dataset table.
    butler_data_id = dict(ref.dataId.required)
    for captured_dimension in ("instrument", "visit"):
        butler_data_id.pop(captured_dimension, None)

    return {
        "id": ref.id,
        "origin": origin,
        "dataset_type": ref.datasetType.name,
        "instrument": ref.dataId.get("instrument"),
        "visit": visit_mapper.get_visit_id(ref),
        "butler_data_id": butler_data_id,
        "embargo_status": DatasetLocationStatus.PRESENT,
    }


class _VisitMapper:
    """Provides a mapping from Butler "exposure" and "group" dimensions to the
    corresponding "visit" records.

    Parameters
    ----------
    butler
        Butler instance that will be used to look up the mapping.
    datasets
        List of datasets that we will look up the visit records for.

    Notes
    -----
    Butler has three seperate dimensions that map to the concept of "visit":
    "visit", "exposure", and "group".  In Prompt Processing, group
    corresponds 1:1 with exposure, and exposure corresponds 1:1 with
    visit.  For the purpose of publication, we want to identify everything by
    visit, so we look up the visits corresponding to these other dimensions
    here.
    """

    def __init__(self, butler: Butler, datasets: list[DatasetRef]) -> None:
        group_ids = _find_matching_data_ids("group", datasets)
        exposure_ids = _find_matching_data_ids("exposure", datasets)
        visit_ids = _find_matching_data_ids("visit", datasets)

        # Look up all the exposure IDs corresponding to the datasets for which
        # we only have group IDs.
        with butler.query() as query:
            exposures_from_groups: Iterable[DataCoordinate] = (
                query.join_data_coordinates(group_ids).data_ids(["instrument", "exposure"])
                if group_ids
                else []
            )
            exposure_ids.update(exposures_from_groups)

        # Look up all the visit IDs corresponding to exposure IDs known from
        # datasets or groups.
        with butler.query() as query:
            visits_from_exposures = (
                list(
                    query.join_dimensions("visit_definition")
                    .join_data_coordinates(exposure_ids)
                    .data_ids(["instrument", "exposure", "visit"])
                )
                if exposure_ids
                else []
            )

            self._exposure_visit_mapping = {
                id.subset("exposure"): id.subset("visit") for id in visits_from_exposures
            }
            self._group_visit_mapping = {
                id.subset("group"): id.subset("visit") for id in visits_from_exposures
            }
            visit_ids.update(id.subset("visit") for id in visits_from_exposures)

        # Look up the dimension records for all visits referenced by the input datasets.
        with butler.query() as query:
            self._visit_records = (
                {
                    record.dataId: record
                    for record in query.join_data_coordinates(visit_ids).dimension_records("visit")
                }
                if visit_ids
                else {}
            )

    def get_visit_record(self, ref: DatasetRef) -> DimensionRecord:
        """Return the visit record corresponding to the given dataset."""
        visit_id = _get_dimension_data_id("visit", ref)
        if visit_id is None:
            exposure_id = _get_dimension_data_id("exposure", ref)
            if exposure_id is not None:
                visit_id = self._exposure_visit_mapping.get(exposure_id)
        if visit_id is None:
            group_id = _get_dimension_data_id("group", ref)
            if group_id is not None:
                visit_id = self._group_visit_mapping.get(group_id)

        if visit_id is not None:
            visit_record = self._visit_records.get(visit_id)
            if visit_record is not None:
                return visit_record

        raise ValueError(f"Failed to find visit record corresponding to dataset {ref}.")

    def get_visit_id(self, ref: DatasetRef) -> int:
        """Return the visit ID corresponding to the given dataset."""
        visit_id = self.get_visit_record(ref).dataId["visit"]
        assert isinstance(visit_id, int), "Visit IDs are expected to be integers"
        return visit_id

    def get_all_visit_records(self) -> Iterable[DimensionRecord]:
        """Return all visit records referenced by the input datasets."""
        return self._visit_records.values()


def _find_matching_data_ids(dimension: str, datasets: list[DatasetRef]) -> set[DataCoordinate]:
    data_ids: set[DataCoordinate] = set()
    for ref in datasets:
        if (id := _get_dimension_data_id(dimension, ref)) is not None:
            data_ids.add(id)
    return data_ids


def _get_dimension_data_id(dimension: str, ref: DatasetRef) -> DataCoordinate | None:
    if dimension in ref.datasetType.dimensions.required:
        return ref.dataId.subset([dimension])
    else:
        return None
