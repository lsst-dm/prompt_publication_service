import unittest

import sqlalchemy

from lsst.daf.butler import Butler, CollectionType, DatasetId
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

    async def _set_up_dataset(self, dataset_type: str, data_id: dict[str, str | int]) -> DatasetId:
        """Create a dataset in the prompt_prep repo and register it in the
        state database.
        """
        ref = self.prompt_prep_butler.put(_BUTLER_PUT_PAYLOAD, dataset_type, dataId=data_id)
        await register_embargo_datasets(
            self.ctx.state_database, DatasetOrigin.PROMPT_PROCESSING, self.prompt_prep_butler, [ref]
        )
        return ref.id

    async def _mark_dataset_present_in_prompt_prep(self, dataset_id: DatasetId) -> None:
        async with self.ctx.state_database.session() as session:
            query = (
                sqlalchemy.update(Dataset)
                .where(Dataset.id == dataset_id)
                .values(prompt_prep_status=DatasetLocationStatus.PRESENT)
            )
            await session.execute(query)
            await session.commit()

    async def test_publish(self) -> None:
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
        self.assertIsNone(self.google_butler.get_dataset(visit1_10))
        self.assertIsNone(self.google_butler.get_dataset(visit1_10_unpublished))

        # Mark the remaining published dataset present, and visit publication
        # should proceed.
        await self._mark_dataset_present_in_prompt_prep(visit1_11)
        await publish_to_google_task.run(self.ctx)
        self.assertEqual(
            (await get_visit_state(self.ctx, VISIT1.id)).google_int_status,
            VisitPublicationStatus.PUBLISHED,
        )
        ref = self.google_butler.get_dataset(visit1_10)
        assert ref is not None
        self.assertEqual(self.google_butler.get(ref), _BUTLER_PUT_PAYLOAD)
        self.assertIsNotNone(self.google_butler.get_dataset(visit1_11))
        self.assertIsNone(self.google_butler.get_dataset(visit1_10_unpublished))
        self.assertIsNone(self.google_butler.get_dataset(visit1_11_unpublished))

        # Verify that each visit's state is tracked separately.
        self.assertEqual(
            (await get_visit_state(self.ctx, VISIT2.id)).google_int_status,
            VisitPublicationStatus.NEVER_PRESENT,
        )
