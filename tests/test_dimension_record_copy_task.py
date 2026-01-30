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

import unittest

from lsst.prompt_publication_service.tasks.dimension_record_copy import DimensionRecordCopyTask
from lsst.prompt_publication_service.schema import Visit, Exposure
from lsst.prompt_publication_service.test_utils import (
    setup_task_context_with_empty_repos,
    load_base_dimension_data,
    load_visit_dimension_data,
    VISIT1,
    VISIT2,
    EXPOSURE1,
)


class TestDimensionRecordCopy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.context = await self.enterAsyncContext(
            setup_task_context_with_empty_repos(["embargo", "prompt_prep", "/repo/main"])
        )
        self.butler_factory = self.context.butler_factory
        self.state_db = self.context.state_database
        load_base_dimension_data(self.butler_factory.create_butler("embargo"))
        load_visit_dimension_data(self.butler_factory.create_butler("embargo"))
        self.prompt_prep_butler = self.butler_factory.create_butler("prompt_prep")
        self.repo_main_butler = self.butler_factory.create_butler("/repo/main")

    async def test_dimension_record_copy_visit(self) -> None:
        async with self.state_db.session() as session:
            session.add_all(
                [
                    Visit(id=VISIT1.id, instrument="LSSTCam", day_obs=20251202, time=None),
                    Visit(id=VISIT2.id, instrument="LSSTCam", day_obs=20251202, time=None),
                ]
            )
            await session.commit()

        prompt_prep_task = DimensionRecordCopyTask(Visit, "embargo", "prompt_prep")
        repo_main_task = DimensionRecordCopyTask(Visit, "prompt_prep", "/repo/main")

        # prompt_prep is still empty, so there is nothing to copy from it.
        self.assertEqual((await repo_main_task.run(self.context)).data, 0)

        # Copy from embargo to prompt_prep.  In addition to the visit records
        # themselves, it should transfer all associated records.
        self.assertEqual((await prompt_prep_task.run(self.context)).data, 2)
        self.assertEqual(len(self.prompt_prep_butler.query_dimension_records("visit")), 2)
        self.assertEqual(len(self.prompt_prep_butler.query_dimension_records("visit_detector_region")), 4)
        self.assertEqual(len(self.prompt_prep_butler.query_dimension_records("visit_definition")), 2)
        self.assertEqual(len(self.prompt_prep_butler.query_dimension_records("exposure")), 2)

        # Running a second time finds nothing left to copy.
        self.assertEqual((await prompt_prep_task.run(self.context)).data, 0)

        # Transfer to /repo/main now picks up the records from prompt_prep
        self.assertEqual((await repo_main_task.run(self.context)).data, 2)
        self.assertEqual(len(self.repo_main_butler.query_dimension_records("visit")), 2)
        self.assertEqual(len(self.repo_main_butler.query_dimension_records("visit_detector_region")), 4)
        self.assertEqual(len(self.repo_main_butler.query_dimension_records("visit_definition")), 2)
        self.assertEqual(len(self.repo_main_butler.query_dimension_records("exposure")), 2)

    async def test_dimension_record_copy_exposure(self) -> None:
        async with self.state_db.session() as session:
            session.add_all(
                [
                    Exposure(
                        id=EXPOSURE1.id, instrument="LSSTCam", day_obs=20251202, can_see_sky=True, time=None
                    ),
                ]
            )
            await session.commit()

        task = DimensionRecordCopyTask(Exposure, "embargo", "prompt_prep")
        self.assertEqual((await task.run(self.context)).data, 1)
        self.assertEqual(len(self.prompt_prep_butler.query_dimension_records("exposure")), 1)
        self.assertEqual(len(self.repo_main_butler.query_dimension_records("visit", explain=False)), 0)
