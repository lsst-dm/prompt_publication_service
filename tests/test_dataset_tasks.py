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

from lsst.daf.butler import LabeledButlerFactory, Butler

from lsst.prompt_publication_service.configs.prompt_processing_outputs import PROMPT_PROCESSING_OUTPUT_CONFIG
from lsst.prompt_publication_service.register import register_embargo_datasets
from lsst.prompt_publication_service.schema import DatasetOrigin, Dataset, DatasetLocationStatus
from lsst.prompt_publication_service.tasks.transfer import unembargo_transfer_task, repo_main_transfer_task
from lsst.prompt_publication_service.test_utils import (
    create_butler_repo,
    create_publication_state_db,
    load_test_dimension_data,
    register_test_dataset_types,
    NONVISIT_DATASET_TYPE,
    VISIT_DATASET_TYPE,
    VISIT1,
    VISIT2,
)
from lsst.prompt_publication_service.date_time_source import DateTimeSource
from sqlalchemy import select


class TestDatasetTransfer(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        embargo_repo = self.enterContext(create_butler_repo())
        prompt_prep_repo = self.enterContext(create_butler_repo())
        main_repo = self.enterContext(create_butler_repo())
        self.butler_factory = self.enterContext(
            LabeledButlerFactory(
                {"embargo": embargo_repo, "prompt_prep": prompt_prep_repo, "/repo/main": main_repo},
                writeable=True,
            )
        )
        self.embargo_butler = self.enterContext(Butler.from_config(embargo_repo, run="run"))
        load_test_dimension_data(self.embargo_butler)
        register_test_dataset_types(self.embargo_butler)
        self.prompt_prep_butler = self.enterContext(self.butler_factory.create_butler("prompt_prep"))
        load_test_dimension_data(self.prompt_prep_butler)
        self.main_butler = self.enterContext(self.butler_factory.create_butler("/repo/main"))
        load_test_dimension_data(self.main_butler)

    async def asyncSetUp(self) -> None:
        self.state_db = await self.enterAsyncContext(create_publication_state_db())

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
        # Non-pixel dataset that can be unembargoed immediately.
        nonvisit = self.embargo_butler.put(
            3, NONVISIT_DATASET_TYPE, instrument="LSSTCam", detector=10, group="2025-12-03T07:58:25.583"
        )

        datasets = [pvi1, pvi2, nonvisit]
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
                await repo_main_transfer_task.run(
                    PROMPT_PROCESSING_OUTPUT_CONFIG, self.butler_factory, self.state_db
                ),
                [],
            )
            # Still in the embargo period, so non-pixel data can be unembargoed
            # but the pixel data cannot.
            self.assertEqual(
                await unembargo_transfer_task.run(
                    PROMPT_PROCESSING_OUTPUT_CONFIG,
                    self.butler_factory,
                    self.state_db,
                ),
                [nonvisit.id],
            )
            # Non-pixel dataset is copied from embargo repo to prompt_prep
            # repo.
            self.assertEqual(self.prompt_prep_butler.get(nonvisit), 3)
            self.assertEqual(self.embargo_butler.get(nonvisit), 3)
            self.assertNotEqual(
                self.prompt_prep_butler.getURI(nonvisit), self.embargo_butler.getURI(nonvisit)
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
            self.assertEqual(
                await repo_main_transfer_task.run(
                    PROMPT_PROCESSING_OUTPUT_CONFIG, self.butler_factory, self.state_db
                ),
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
                await unembargo_transfer_task.run(
                    PROMPT_PROCESSING_OUTPUT_CONFIG,
                    self.butler_factory,
                    self.state_db,
                ),
                [],
            )
            self.assertEqual(
                await repo_main_transfer_task.run(
                    PROMPT_PROCESSING_OUTPUT_CONFIG, self.butler_factory, self.state_db
                ),
                [],
            )

        with DateTimeSource.mock_current_time(between_visit_time, 80) as time:
            # Embargo period is finished for the first visit, but not the
            # second.
            self.assertEqual(
                await unembargo_transfer_task.run(
                    PROMPT_PROCESSING_OUTPUT_CONFIG,
                    self.butler_factory,
                    self.state_db,
                ),
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

        # Remove first dataset from both registry and datastore.
        self.embargo_butler.pruneDatasets([ref1], disassociate=True, unstore=True, purge=True)
        # Remove second dataset from datastore only.  The Butler reports
        # datasets as missing differently in this case, versus the above where
        # it was fully removed.
        self.embargo_butler.pruneDatasets([ref2], disassociate=False, unstore=True)

        # The first two datasets are missing, so only the third gets
        # unembargoed.
        self.assertEqual(
            await unembargo_transfer_task.run(
                PROMPT_PROCESSING_OUTPUT_CONFIG,
                self.butler_factory,
                self.state_db,
            ),
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
            await repo_main_transfer_task.run(
                PROMPT_PROCESSING_OUTPUT_CONFIG, self.butler_factory, self.state_db
            ),
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
            await unembargo_transfer_task.run(
                PROMPT_PROCESSING_OUTPUT_CONFIG,
                self.butler_factory,
                self.state_db,
            ),
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
            await repo_main_transfer_task.run(
                PROMPT_PROCESSING_OUTPUT_CONFIG,
                self.butler_factory,
                self.state_db,
            ),
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
