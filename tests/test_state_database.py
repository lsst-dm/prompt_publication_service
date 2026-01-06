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

from sqlalchemy import select
from uuid import UUID
import json
import tempfile
import unittest

from lsst.daf.butler import Butler
from lsst.prompt_publication_service.register import register_dataset_batch_file
from lsst.prompt_publication_service.schema import (
    DatasetOrigin,
    Dataset,
    Visit,
    DatasetLocationStatus,
    UnknownDataset,
)
from lsst.prompt_publication_service.test_utils import (
    create_butler_repo,
    create_publication_state_db,
    load_test_dimension_data,
    register_test_dataset_types,
    VISIT1,
    VISIT2,
    VISIT_DATASET_TYPE,
    NONVISIT_DATASET_TYPE,
)


class TestRegistration(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        repo = self.enterContext(create_butler_repo())
        self.butler = self.enterContext(Butler.from_config(repo, run="run"))
        load_test_dimension_data(self.butler)
        register_test_dataset_types(self.butler)

    async def asyncSetUp(self) -> None:
        self.db = await self.enterAsyncContext(create_publication_state_db())

    async def test_register_datasets(self) -> None:
        pvi1 = self.butler.put(10, VISIT_DATASET_TYPE, instrument="LSSTCam", visit=VISIT1.id, detector=10)
        pvi2 = self.butler.put(11, VISIT_DATASET_TYPE, instrument="LSSTCam", visit=VISIT2.id, detector=11)
        rti = self.butler.put(
            2, NONVISIT_DATASET_TYPE, instrument="LSSTCam", detector=10, group="2025-12-03T07:58:25.583"
        )

        batch_data = {
            "batch_id": "59643df0-e0ed-445c-9fbe-417b526eab6b",
            "datasets": [
                *(str(ref.id) for ref in [pvi1, pvi2, rti]),
                # An arbitrary dataset ID that is not present in the Butler
                # database.
                "f3b0055f-7375-4154-b1e4-922656c0af44",
            ],
        }
        fh = self.enterContext(tempfile.NamedTemporaryFile("w", delete_on_close=False))
        fh.write(json.dumps(batch_data))
        fh.close()
        batch_file = fh.name

        async def register_datasets() -> None:
            with self.assertLogs("lsst.prompt_publication_service.register", level="WARNING") as logged:
                await register_dataset_batch_file(
                    self.db, DatasetOrigin.PROMPT_PROCESSING, self.butler, batch_file
                )
            self.assertEqual(len(logged.output), 1)
            self.assertIn("not found", logged.output[0])
            self.assertIn("f3b0055f-7375-4154-b1e4-922656c0af44", logged.output[0])

        async def check_datasets() -> None:
            async with self.db.session() as session:
                datasets = list(await session.scalars(select(Dataset)))
                datasets.sort(key=lambda dataset: (dataset.dataset_type, dataset.visit))
            self.assertEqual(len(datasets), 3)

            self.assertEqual(datasets[0].id, pvi1.id)
            self.assertIs(datasets[0].origin, DatasetOrigin.PROMPT_PROCESSING)
            self.assertEqual(datasets[0].dataset_type, "preliminary_visit_image")
            self.assertEqual(datasets[0].instrument, "LSSTCam")
            self.assertEqual(datasets[0].visit, VISIT1.id)
            self.assertIs(datasets[0].embargo_status, DatasetLocationStatus.PRESENT)
            self.assertIs(datasets[0].prompt_prep_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(datasets[0].repo_main_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(datasets[0].google_int_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(datasets[0].google_prod_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIsNone(datasets[0].unembargo_time)

            self.assertEqual(datasets[1].id, pvi2.id)
            self.assertIs(datasets[1].origin, DatasetOrigin.PROMPT_PROCESSING)
            self.assertEqual(datasets[1].dataset_type, "preliminary_visit_image")
            self.assertEqual(datasets[1].instrument, "LSSTCam")
            self.assertEqual(datasets[1].visit, VISIT2.id)
            self.assertIs(datasets[1].embargo_status, DatasetLocationStatus.PRESENT)
            self.assertIs(datasets[1].prompt_prep_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(datasets[1].repo_main_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(datasets[1].google_int_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(datasets[1].google_prod_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIsNone(datasets[1].unembargo_time)

            self.assertEqual(datasets[2].id, rti.id)
            self.assertEqual(datasets[2].origin, DatasetOrigin.PROMPT_PROCESSING)
            self.assertEqual(datasets[2].dataset_type, NONVISIT_DATASET_TYPE)
            self.assertEqual(datasets[2].instrument, "LSSTCam")
            self.assertIsNone(datasets[2].visit)
            self.assertIs(datasets[2].embargo_status, DatasetLocationStatus.PRESENT)
            self.assertIs(datasets[2].prompt_prep_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(datasets[2].repo_main_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(datasets[2].google_int_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(datasets[2].google_prod_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIsNone(datasets[2].unembargo_time)

            async with self.db.session() as session:
                unknowns = list(await session.scalars(select(UnknownDataset)))
            self.assertEqual(len(unknowns), 1)
            self.assertEqual(unknowns[0].id, UUID("f3b0055f-7375-4154-b1e4-922656c0af44"))
            self.assertEqual(unknowns[0].origin, DatasetOrigin.PROMPT_PROCESSING)
            self.assertIn(batch_data["batch_id"], unknowns[0].error)

        await register_datasets()
        await check_datasets()

        async with self.db.session() as session:
            visits = list(await session.scalars(select(Visit)))
            visits.sort(key=lambda visit: visit.visit)

        self.assertEqual(len(visits), 2)

        self.assertEqual(visits[0].visit, VISIT1.id)
        self.assertEqual(visits[0].instrument, "LSSTCam")
        self.assertEqual(visits[0].time, VISIT1.time)

        self.assertEqual(visits[1].visit, VISIT2.id)
        self.assertEqual(visits[1].instrument, "LSSTCam")
        self.assertEqual(visits[1].time, VISIT2.time)

        # Dataset registration is idempotent.
        await register_datasets()
        await check_datasets()
        # If any state has changed, re-registering a dataset should not change
        # it.
        async with self.db.session() as session:
            dataset = await session.scalar(select(Dataset).where(Dataset.id == pvi1.id))
            assert dataset is not None
            dataset.prompt_prep_status = DatasetLocationStatus.PRESENT
            await session.commit()
        await register_datasets()
        async with self.db.session() as session:
            dataset = await session.scalar(select(Dataset).where(Dataset.id == pvi1.id))
            assert dataset is not None
            self.assertEqual(dataset.prompt_prep_status, DatasetLocationStatus.PRESENT)
