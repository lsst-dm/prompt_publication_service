import asyncio
from collections.abc import Iterable

from sqlalchemy import delete, insert, update

from lsst.daf.butler import Butler, DatasetRef

from .config import DatasetTypeConfiguration
from .database import Database
from .logging import get_global_logger
from .register import add_dayobs_rows, register_embargo_datasets
from .schema import DayObs, DaytimeApStatus, PublishableDataset

_LOG = get_global_logger()


async def register_daytime_ap_output(
    db: Database, source_butler: Butler, config: DatasetTypeConfiguration, day_obs: int, collection: str
) -> None:
    """Register a daytime AP collection chain into the state database.  All
    datasets of types tracked by this service will be registered as candidates
    for unembargo, and the "find-first" datasets will be registered as candidates
    for publication.

    If this is called a second time the same day_obs, the list of candidates
    for publication will be overwritten by the collection chain from the second
    call.  Additional candidates for unembargo will be appended without
    overwriting.

    Parameters
    ----------
    db
        Connection to prompt publication state database.
    source_butler
        Butler instance that will be used to query for datasets (usually from
        the embargo repo.)
    config
        Configuration defining which dataset types will be tracked in the state
        database.
    day_obs
        Observation date as a Butler day_obs value.
    collection
        Collection that will be queried to find datasets to be registered in
        state database.
    """

    _LOG.bind(task="register daytime ap", day_obs=day_obs, collection=collection)
    _LOG.info("starting dataset lookup")
    # First find all the datasets of the types we manage in the given
    # collection.  This may include "shadowed" datasets from deeper in the
    # chain that will not ultimately be published, but which we still need
    # to clean up from embargo.
    all_datasets = await _query_datasets(
        butler=source_butler,
        collection=collection,
        dataset_types=config.dataset_types(),
        find_first=False,
    )
    _LOG.info("found datasets", count=len(all_datasets))
    # Then find only the "find-first", "best" versions of the dataset types
    # that get published to end users.
    publishable_dataset_types = config.filter(lambda x: x.publish_to_public).dataset_types()
    publishable_datasets = await _query_datasets(
        butler=source_butler,
        collection=collection,
        dataset_types=publishable_dataset_types,
        find_first=True,
    )
    _LOG.info("found publishable datasets", count=len(publishable_datasets))

    _LOG.info("recording datasets in state DB")
    await register_embargo_datasets(db, source_butler, all_datasets)
    async with db.session() as session:
        # Ensure that the dayobs row exists.
        # (Normally it should be created during dataset registration, but
        # if there are no visit-level datasets it might not exist yet.)
        await add_dayobs_rows(db, session, [day_obs])

        # Delete the existing list of datasets for the day_obs, so that a
        # subsequent message with a new or revised collection overrides the
        # original list.
        await session.execute(delete(PublishableDataset).where(PublishableDataset.day_obs == day_obs))

        # Insert the list of datasets to be published.
        dataset_rows = [{"day_obs": day_obs, "dataset_id": ref.id} for ref in publishable_datasets]
        await session.execute(insert(PublishableDataset), dataset_rows)

        # Mark daytime AP completed for this day_obs.
        await session.execute(
            update(DayObs).where(DayObs.id == day_obs), {"daytime_ap_status": DaytimeApStatus.COMPLETED}
        )

        await session.commit()
    _LOG.info("finished recording datasets in state DB")


async def _query_datasets(
    butler: Butler, collection: str, dataset_types: Iterable[str], find_first: bool
) -> list[DatasetRef]:
    def query_sync() -> list[DatasetRef]:
        missing_types: list[str] = []
        resolved_types = butler.registry.queryDatasetTypes(dataset_types, missing=missing_types)
        if missing_types:
            _LOG.warning(f"Configured dataset types not found in Butler repository: {missing_types}")
        return butler.query_all_datasets(
            collection, name=[dt.name for dt in resolved_types], find_first=find_first, limit=None
        )

    return await asyncio.to_thread(query_sync)
