import unittest

import sqlalchemy

from lsst.daf.butler import Butler, CollectionType, DatasetRef
from lsst.prompt_publication_service.register import register_embargo_datasets
from lsst.prompt_publication_service.schema import (
    Dataset,
    DatasetLocationStatus,
    DatasetOrigin,
    VisitPublicationStatus,
)
from lsst.prompt_publication_service.tasks.base import TaskContext
from lsst.prompt_publication_service.tasks.publish_to_google import (
    OUTPUT_TAGGED_COLLECTION,
    publish_to_google_task,
)
from lsst.prompt_publication_service.test_utils import (
    UNPUBLISHED_VISIT_DATASET_TYPE,
    VISIT1,
    VISIT2,
    VISIT_DATASET_TYPE,
    get_dataset_state,
    get_visit_state,
    load_base_dimension_data,
    load_visit_dimension_data,
    register_test_dataset_types,
    setup_task_context_with_empty_repos,
)

_BUTLER_PUT_PAYLOAD = 123


class TestDatasetTransfer(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.ctx: TaskContext = await self.enterAsyncContext(setup_task_context_with_empty_repos())
        self.prompt_prep_butler: Butler = self.enterContext(
            self.ctx.butler_factory.create_butler("prompt_prep")
        ).clone(run="run")
        load_base_dimension_data(self.prompt_prep_butler)
        load_visit_dimension_data(self.prompt_prep_butler)
        register_test_dataset_types(self.prompt_prep_butler)
        self.google_butler: Butler = self.enterContext(
            self.ctx.butler_factory.create_butler("prompt_google_int")
        )
        load_base_dimension_data(self.google_butler)
        self.google_butler.collections.register(OUTPUT_TAGGED_COLLECTION, CollectionType.TAGGED)

    async def _set_up_dataset(self, dataset_type: str, data_id: dict[str, str | int]) -> DatasetRef:
        """Create a dataset in the prompt_prep repo and register it in the
        state database.
        """
        ref = self.prompt_prep_butler.put(_BUTLER_PUT_PAYLOAD, dataset_type, dataId=data_id)
        await register_embargo_datasets(
            self.ctx.state_database, DatasetOrigin.PROMPT_PROCESSING, self.prompt_prep_butler, [ref]
        )
        return ref

    async def _mark_dataset_present_in_prompt_prep(self, ref: DatasetRef) -> None:
        async with self.ctx.state_database.session() as session:
            query = (
                sqlalchemy.update(Dataset)
                .where(Dataset.id == ref.id)
                .values(prompt_prep_status=DatasetLocationStatus.PRESENT)
            )
            await session.execute(query)
            await session.commit()

    async def test_publish(self) -> None:
        """Test basic functionality of visit publication, confirming that
        datasets aren't published until all datasets for the visit are
        available and that each visit is published separately.
        """
        # Two datasets that will be published together for a single visit.
        visit1_10 = await self._set_up_dataset(
            VISIT_DATASET_TYPE, {"instrument": "LSSTCam", "visit": VISIT1.id, "detector": 10}
        )
        visit1_11 = await self._set_up_dataset(
            VISIT_DATASET_TYPE, {"instrument": "LSSTCam", "visit": VISIT1.id, "detector": 11}
        )
        # Another two datasets from the same visit that won't be published.
        visit1_10_unpublished = await self._set_up_dataset(
            UNPUBLISHED_VISIT_DATASET_TYPE, {"instrument": "LSSTCam", "visit": VISIT1.id, "detector": 10}
        )
        visit1_11_unpublished = await self._set_up_dataset(
            UNPUBLISHED_VISIT_DATASET_TYPE, {"instrument": "LSSTCam", "visit": VISIT1.id, "detector": 11}
        )
        # Dataset from a different visit.
        await self._set_up_dataset(
            VISIT_DATASET_TYPE, {"instrument": "LSSTCam", "visit": VISIT2.id, "detector": 11}
        )

        # Visit requires all known publishable datasets to be present before
        # publication proceeds.
        await self._mark_dataset_present_in_prompt_prep(visit1_10)
        await self._mark_dataset_present_in_prompt_prep(visit1_10_unpublished)
        await publish_to_google_task.run(self.ctx)
        self.assertEqual(
            (await get_visit_state(self.ctx, VISIT1.id)).google_int_status,
            VisitPublicationStatus.NEVER_PRESENT,
        )
        self.assertIsNone(self.google_butler.get_dataset(visit1_10.id))
        self.assertIsNone(self.google_butler.get_dataset(visit1_10_unpublished.id))

        # Mark the remaining publishable dataset present, and visit publication
        # should proceed.
        await self._mark_dataset_present_in_prompt_prep(visit1_11)
        await publish_to_google_task.run(self.ctx)
        self.assertEqual(
            (await get_visit_state(self.ctx, VISIT1.id)).google_int_status,
            VisitPublicationStatus.PUBLISHED,
        )
        self.assertEqual(self.google_butler.get(visit1_10), _BUTLER_PUT_PAYLOAD)
        self.assertIsNotNone(self.google_butler.get_dataset(visit1_11.id))
        self.assertIsNone(self.google_butler.get_dataset(visit1_10_unpublished.id))
        self.assertIsNone(self.google_butler.get_dataset(visit1_11_unpublished.id))
        self.assertCountEqual(
            [visit1_10, visit1_11],
            self.google_butler.query_datasets(VISIT_DATASET_TYPE, OUTPUT_TAGGED_COLLECTION),
        )

        # Verify that each visit's state is tracked separately.
        self.assertEqual(
            (await get_visit_state(self.ctx, VISIT2.id)).google_int_status,
            VisitPublicationStatus.NEVER_PRESENT,
        )

    async def test_publish_incomplete_visit(self) -> None:
        """Test that if datasets are missing when we attempt to publish a
        visit, the visit is not published and marked as incomplete.
        """
        # Set up a single visit dataset, then delete it from the prompt prep
        # repo.
        ref = await self._set_up_dataset(
            VISIT_DATASET_TYPE, {"instrument": "LSSTCam", "visit": VISIT1.id, "detector": 10}
        )
        await self._mark_dataset_present_in_prompt_prep(ref)
        self.prompt_prep_butler.pruneDatasets([ref], unstore=True, purge=True)

        await publish_to_google_task.run(self.ctx)
        # Visit is marked incomplete, and records are not transferred to
        # Google.
        self.assertEqual(
            (await get_visit_state(self.ctx, VISIT1.id)).google_int_status,
            VisitPublicationStatus.INCOMPLETE,
        )
        self.assertEqual(
            [],
            self.google_butler.query_dimension_records(
                "visit", data_id={"instrument": "LSSTCam", "visit": VISIT1.id}, explain=False
            ),
        )

    async def test_publish_idempotency(self) -> None:
        """Verify that publication is considered successful even if a previous
        attempt updated the target Butler but failed before updating the state
        database."""
        ref = await self._set_up_dataset(
            VISIT_DATASET_TYPE, {"instrument": "LSSTCam", "visit": VISIT1.id, "detector": 10}
        )
        await self._mark_dataset_present_in_prompt_prep(ref)
        self.google_butler.transfer_from(
            self.prompt_prep_butler,
            [ref],
            "unsafe_direct",
            register_dataset_types=True,
            transfer_dimensions=True,
        )
        self.google_butler.registry.associate(OUTPUT_TAGGED_COLLECTION, [ref])
        await publish_to_google_task.run(self.ctx)

        self.assertEqual(
            (await get_visit_state(self.ctx, VISIT1.id)).google_int_status,
            VisitPublicationStatus.PUBLISHED,
        )
        self.assertEqual(
            (await get_dataset_state(self.ctx, ref.id)).google_int_status, DatasetLocationStatus.PRESENT
        )
