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

import os
import unittest
from datetime import timedelta
from uuid import UUID

from lsst.daf.butler import Butler

from lsst.prompt_publication_service.register import register_embargo_datasets
from lsst.prompt_publication_service.schema import (
    DatasetOrigin,
    Dataset,
    DatasetLocationStatus,
    Exposure,
    Group,
    Visit,
)
from lsst.prompt_publication_service.tasks.dimension_record_copy import DimensionRecordCopyTask
from lsst.prompt_publication_service.tasks.transfer import unembargo_transfer_task, repo_main_transfer_task
from lsst.prompt_publication_service.test_utils import (
    setup_task_context_with_empty_repos,
    load_base_dimension_data,
    load_visit_dimension_data,
    register_test_dataset_types,
    EXPOSURE_DATASET_TYPE,
    EXPOSURE1,
    NONVISIT_DATASET_TYPE,
    VISIT_DATASET_TYPE,
    VISIT1,
    VISIT2,
)
from lsst.prompt_publication_service.date_time_source import DateTimeSource
from sqlalchemy import select


class TestDatasetTransfer(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.context = await self.enterAsyncContext(
            setup_task_context_with_empty_repos(["embargo", "prompt_prep", "/repo/main"])
        )
        self.butler_factory = self.context.butler_factory
        self.state_db = self.context.state_database
        self.embargo_butler: Butler = self.enterContext(
            self.butler_factory.create_butler("embargo").clone(run="run")
        )
        load_base_dimension_data(self.embargo_butler)
        load_visit_dimension_data(self.embargo_butler)
        register_test_dataset_types(self.embargo_butler)
        self.prompt_prep_butler = self.enterContext(self.butler_factory.create_butler("prompt_prep"))
        load_base_dimension_data(self.prompt_prep_butler)
        self.main_butler = self.enterContext(self.butler_factory.create_butler("/repo/main"))
        load_base_dimension_data(self.main_butler)

    async def test_unembargo(self) -> None:
        """Test the basic functionality of the unembargo process."""

        # Pixel datasets that have to wait out the embargo period before they
        # can be copied out of the embargo repo.
        pvi1 = self.embargo_butler.put(
            1, VISIT_DATASET_TYPE, instrument="LSSTCam", visit=VISIT1.id, detector=10
        )
        pvi2 = self.embargo_butler.put(
            2, VISIT_DATASET_TYPE, instrument="LSSTCam", visit=VISIT2.id, detector=11
        )
        # Non-pixel dataset that can be unembargoed immediately, but requires
        # exposure records prior to the dataset transfer.
        exposure = self.embargo_butler.put(
            1, EXPOSURE_DATASET_TYPE, instrument="LSSTCam", exposure=EXPOSURE1.id, detector=10
        )
        # Non-pixel dataset that can be unembargoed immediately with no
        # prerequisites.
        nonvisit = self.embargo_butler.put(
            3, NONVISIT_DATASET_TYPE, instrument="LSSTCam", detector=10, group="2025-12-03T07:58:25.583"
        )

        datasets = [pvi1, pvi2, nonvisit, exposure]
        await register_embargo_datasets(
            self.state_db, DatasetOrigin.PROMPT_PROCESSING, self.embargo_butler, datasets
        )

        # Time that is after the end of the first visit, but before the end of
        # the second visit.
        between_visit_time = VISIT1.time + timedelta(seconds=30)

        with DateTimeSource.mock_current_time(between_visit_time, 1) as time1:
            # Nothing has been copied to prompt_prep yet, so there is nothing
            # to copy to /repo/main.
            self.assertEqual(
                (await repo_main_transfer_task.run(self.context)).data,
                [],
            )
            # Still in the embargo period, so non-pixel data can be unembargoed
            # but the pixel data cannot.
            # Initially, we still transfer nothing because the 'group'
            # dimension records haven't been copied...
            self.assertEqual(
                (await unembargo_transfer_task.run(self.context)).data,
                [],
            )
            # And then after the 'group' copy, the non-pixel datasets can go.
            await DimensionRecordCopyTask(Group, "embargo", "prompt_prep").run(self.context)
            self.assertEqual(
                (await unembargo_transfer_task.run(self.context)).data,
                [nonvisit.id],
            )
            # Non-pixel dataset is copied from embargo repo to prompt_prep
            # repo.
            self.assertEqual(self.prompt_prep_butler.get(nonvisit), 3)
            self.assertEqual(self.embargo_butler.get(nonvisit), 3)
            self.assertNotEqual(
                self.prompt_prep_butler.getURI(nonvisit), self.embargo_butler.getURI(nonvisit)
            )

            # The non-pixel dataset requiring exposure records wasn't
            # transferred, because the exposure records weren't transferred
            # yet.  Set up the exposure records, and then it should transfer.
            await DimensionRecordCopyTask(Exposure, "embargo", "prompt_prep").run(self.context)
            self.assertEqual(
                (await unembargo_transfer_task.run(self.context)).data,
                [exposure.id],
            )
            self.assertEqual(self.prompt_prep_butler.get(exposure), 1)
            self.assertEqual(self.embargo_butler.get(exposure), 1)
            self.assertNotEqual(
                self.prompt_prep_butler.getURI(exposure), self.embargo_butler.getURI(exposure)
            )

            # Pixel datasets weren't copied yet -- they're still in the embargo
            # period.
            self.assertIsNone(self.prompt_prep_butler.get_dataset(pvi1.id))
            self.assertIsNone(self.prompt_prep_butler.get_dataset(pvi2.id))
            # State has been updated and the unembargo time recorded for the
            # non-pixel dataset.
            nonvisit_state = await self._get_dataset_state(nonvisit.id)
            self.assertEqual(nonvisit_state.unembargo_time, time1)
            self.assertEqual(nonvisit_state.prompt_prep_status, DatasetLocationStatus.PRESENT)
            # The pixel dataset state is unchanged.
            pvi1_state = await self._get_dataset_state(pvi1.id)
            self.assertIsNone(pvi1_state.unembargo_time)
            self.assertEqual(pvi1_state.prompt_prep_status, DatasetLocationStatus.NEVER_PRESENT)

        with DateTimeSource.mock_current_time(between_visit_time, 2):
            # Now that there is a dataset in prompt_prep, it should move to
            # /repo/main.
            await DimensionRecordCopyTask(Group, "prompt_prep", "/repo/main").run(self.context)
            self.assertEqual(
                (await repo_main_transfer_task.run(self.context)).data,
                [nonvisit.id],
            )
            state = await self._get_dataset_state(nonvisit.id)
            self.assertEqual(state.repo_main_status, DatasetLocationStatus.PRESENT)
            self.assertEqual(self.main_butler.get(nonvisit), 3)
            # Files are hardlinked in /repo/main from prompt_prep.
            main_path = self.main_butler.getURI(nonvisit).ospath
            prompt_prep_path = self.prompt_prep_butler.getURI(nonvisit).ospath
            self.assertNotEqual(main_path, prompt_prep_path)
            self.assertTrue(os.path.samefile(main_path, prompt_prep_path))
            # Unembargo time and prompt_prep status are not modified when
            # copying to /repo/main.
            self.assertEqual(state.unembargo_time, time1)
            self.assertEqual(state.prompt_prep_status, DatasetLocationStatus.PRESENT)

        with DateTimeSource.mock_current_time(between_visit_time, 3) as time:
            # Still in the embargo period.  We already unembargoed the
            # non-pixel data, and there shouldn't be anything else yet.
            self.assertEqual(
                (await unembargo_transfer_task.run(self.context)).data,
                [],
            )
            self.assertEqual(
                (await repo_main_transfer_task.run(self.context)).data,
                [],
            )

        with DateTimeSource.mock_current_time(between_visit_time, 80) as time:
            # Embargo period is finished for the first visit, but not the
            # second.

            # We haven't yet transferred the required visit records to the
            # repository, so we still can't unembargo anything else.
            self.assertEqual(
                (await unembargo_transfer_task.run(self.context)).data,
                [],
            )

            # After transferring the visit records, we can proceed.
            await DimensionRecordCopyTask(Visit, "embargo", "prompt_prep").run(self.context)
            self.assertEqual(
                (await unembargo_transfer_task.run(self.context)).data,
                [pvi1.id],
            )
            # Visit 1 dataset was copied from embargo to prompt_prep.
            self.assertEqual(self.prompt_prep_butler.get(pvi1), 1)
            self.assertEqual(self.embargo_butler.get(pvi1), 1)
            self.assertNotEqual(self.prompt_prep_butler.getURI(pvi1), self.embargo_butler.getURI(pvi1))
            # Visit 2 dataset wasn't copied yet -- it's still (barely) in the
            # embargo period.
            self.assertIsNone(self.prompt_prep_butler.get_dataset(pvi2.id))
            # State for visit 1 was updated.
            pvi1_state = await self._get_dataset_state(pvi1.id)
            self.assertEqual(pvi1_state.unembargo_time, time)
            self.assertEqual(pvi1_state.prompt_prep_status, DatasetLocationStatus.PRESENT)
            # State for visit 2 is unmoidifed.
            pvi2_state = await self._get_dataset_state(pvi2.id)
            self.assertIsNone(pvi2_state.unembargo_time)
            self.assertEqual(pvi2_state.prompt_prep_status, DatasetLocationStatus.NEVER_PRESENT)

    async def test_unembargo_missing_datasets(self) -> None:
        """Test the behavior of unembargo when datasets are missing."""

        ref1 = self.embargo_butler.put(
            1, NONVISIT_DATASET_TYPE, instrument="LSSTCam", detector=10, group="2025-12-03T07:58:25.583"
        )
        ref2 = self.embargo_butler.put(
            2, NONVISIT_DATASET_TYPE, instrument="LSSTCam", detector=11, group="2025-12-03T07:58:25.583"
        )
        ref3 = self.embargo_butler.put(
            3, NONVISIT_DATASET_TYPE, instrument="LSSTCam", detector=10, group="2025-12-03T07:58:10.858"
        )
        await register_embargo_datasets(
            self.state_db, DatasetOrigin.PROMPT_PROCESSING, self.embargo_butler, [ref1, ref2, ref3]
        )
        # Transfer required 'group' records.
        await DimensionRecordCopyTask(Group, "embargo", "prompt_prep").run(self.context)
        await DimensionRecordCopyTask(Group, "prompt_prep", "/repo/main").run(self.context)

        # Remove first dataset from both registry and datastore.
        self.embargo_butler.pruneDatasets([ref1], disassociate=True, unstore=True, purge=True)
        # Remove second dataset from datastore only.  The Butler reports
        # datasets as missing differently in this case, versus the above where
        # it was fully removed.
        self.embargo_butler.pruneDatasets([ref2], disassociate=False, unstore=True)

        # The first two datasets are missing, so only the third gets
        # unembargoed.
        self.assertEqual(
            (await unembargo_transfer_task.run(self.context)).data,
            [ref3.id],
        )

        # The first two datasets are recorded as missing so that we don't try
        # to copy them again later.
        self.assertIsNone(self.prompt_prep_butler.get_dataset(ref1.id))
        state1 = await self._get_dataset_state(ref1.id)
        self.assertEqual(state1.embargo_status, DatasetLocationStatus.MISSING)
        self.assertEqual(state1.prompt_prep_status, DatasetLocationStatus.NEVER_PRESENT)
        self.assertIsNone(state1.unembargo_time)
        self.assertIsNone(self.prompt_prep_butler.get_dataset(ref2.id))
        state2 = await self._get_dataset_state(ref2.id)
        self.assertEqual(state2.embargo_status, DatasetLocationStatus.MISSING)
        self.assertEqual(state2.prompt_prep_status, DatasetLocationStatus.NEVER_PRESENT)
        # Third dataset copied as normal.
        self.assertEqual(self.prompt_prep_butler.get(ref3), 3)
        state3 = await self._get_dataset_state(ref3.id)
        self.assertEqual(state3.embargo_status, DatasetLocationStatus.PRESENT)
        self.assertEqual(state3.prompt_prep_status, DatasetLocationStatus.PRESENT)

        # Make sure dataset missing from prompt_prep is recorded correctly in
        # the state DB.
        self.prompt_prep_butler.pruneDatasets([ref3], disassociate=True, unstore=True, purge=True)
        self.assertEqual(
            (await repo_main_transfer_task.run(self.context)).data,
            [],
        )
        state3 = await self._get_dataset_state(ref3.id)
        self.assertEqual(state3.embargo_status, DatasetLocationStatus.PRESENT)
        self.assertEqual(state3.prompt_prep_status, DatasetLocationStatus.MISSING)
        self.assertEqual(state3.repo_main_status, DatasetLocationStatus.NEVER_PRESENT)

    async def test_unembargo_idempotency(self) -> None:
        """Test behavior of unembargo when a dataset already exists in the
        target repo.
        """
        ref = self.embargo_butler.put(
            1, NONVISIT_DATASET_TYPE, instrument="LSSTCam", detector=10, group="2025-12-03T07:58:25.583"
        )
        await register_embargo_datasets(
            self.state_db, DatasetOrigin.PROMPT_PROCESSING, self.embargo_butler, [ref]
        )
        # Transfer required 'group' records.
        await DimensionRecordCopyTask(Group, "embargo", "prompt_prep").run(self.context)
        await DimensionRecordCopyTask(Group, "prompt_prep", "/repo/main").run(self.context)
        # Copy the dataset to the target Butler.  This simulates the case where
        # unembargo failed partway through, after copying a dataset but before
        # updating the state DB.  Or someone could have transferred a dataset
        # outside the control of this system.
        self.prompt_prep_butler.transfer_from(
            self.embargo_butler, [ref], transfer="copy", register_dataset_types=True
        )
        # Unembargo should report success for the existing dataset, and update
        # the state DB.
        self.assertEqual(
            (await unembargo_transfer_task.run(self.context)).data,
            [ref.id],
        )
        state = await self._get_dataset_state(ref.id)
        self.assertEqual(self.prompt_prep_butler.get(ref), 1)
        self.assertEqual(state.prompt_prep_status, DatasetLocationStatus.PRESENT)

        # Same as above, but for transfer to /repo/main from prompt_prep.
        # This one uses hardlinks instead of copy.
        self.main_butler.transfer_from(
            self.prompt_prep_butler, [ref], transfer="hardlink", register_dataset_types=True
        )
        self.assertEqual(
            (await repo_main_transfer_task.run(self.context)).data,
            [ref.id],
        )
        state = await self._get_dataset_state(ref.id)
        self.assertEqual(self.main_butler.get(ref), 1)
        self.assertEqual(state.repo_main_status, DatasetLocationStatus.PRESENT)

    async def _get_dataset_state(self, dataset_id: UUID) -> Dataset:
        async with self.state_db.session() as session:
            sql = select(Dataset).where(Dataset.id == dataset_id)
            dataset = await session.scalar(sql)
            assert dataset is not None, f"Expected to find dataset '{dataset_id} in the state DB"
            return dataset
