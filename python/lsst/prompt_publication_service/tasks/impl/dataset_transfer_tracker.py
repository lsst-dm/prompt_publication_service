from collections.abc import Iterable

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from lsst.daf.butler import Butler, DatasetId, DatasetRef

from ...date_time_source import DateTimeSource
from ...schema import ButlerRepository, Dataset, DatasetLocationStatus


class DatasetTransferTracker:
    def __init__(
        self,
        *,
        source_repository: ButlerRepository,
        target_repository: ButlerRepository,
    ) -> None:
        self._source_repository = source_repository
        self._target_repository = target_repository
        self._missing_ids: set[DatasetId] = set()
        self._found_ids: set[DatasetId] = set()
        self._completed_ids: set[DatasetId] = set()

    def find_datasets(self, source_butler: Butler, dataset_ids: Iterable[DatasetId]) -> list[DatasetRef]:
        dataset_ids = frozenset(dataset_ids)
        found_refs = source_butler.get_many_datasets(dataset_ids)
        found_ids = frozenset(ref.id for ref in found_refs)
        # Dataset IDs that are not known to the Butler at all
        # (missing from both "registry" and "datastore").
        missing_ids = frozenset(dataset_ids - found_ids)
        self._missing_ids.update(missing_ids)
        self._found_ids.update(found_ids)
        return found_refs

    def get_missing_datasets(self) -> set[DatasetId]:
        return set(self._missing_ids)

    def get_complete_datasets(self) -> set[DatasetId]:
        return set(self._completed_ids)

    def get_incomplete_datasets(self) -> set[DatasetId]:
        return self._found_ids - self._completed_ids

    def mark_datasets_completed(self, dataset_ids: Iterable[DatasetId]) -> None:
        self._completed_ids.update(dataset_ids)

    def mark_refs_completed(self, refs: Iterable[DatasetRef]) -> None:
        self._completed_ids.update(ref.id for ref in refs)

    def mark_incomplete_as_missing(self) -> None:
        self._missing_ids.update(self.get_incomplete_datasets())

    async def persist_transfer_result(
        self,
        session: AsyncSession,
        target_time_column: str | None = None,
    ) -> None:
        transfer_time = DateTimeSource.now()
        source_status_column = Dataset.get_status_column_name(self._source_repository)
        target_status_column = Dataset.get_status_column_name(self._target_repository)

        await session.execute(
            update(Dataset),
            [
                {
                    "id": id,
                    source_status_column: DatasetLocationStatus.MISSING,
                }
                for id in self._missing_ids
            ],
        )

        if target_time_column is None:
            time_update = {}
        else:
            time_update = {target_time_column: transfer_time}
        await session.execute(
            update(Dataset),
            [
                {
                    "id": id,
                    target_status_column: DatasetLocationStatus.PRESENT,
                    **time_update,
                }
                for id in self._completed_ids
            ],
        )
