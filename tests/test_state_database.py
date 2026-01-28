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

from structlog.testing import capture_logs

from lsst.daf.butler import Butler
from lsst.prompt_publication_service.register import register_dataset_batch_file
from lsst.prompt_publication_service.schema import (
    DatasetOrigin,
    Dataset,
    Exposure,
    Visit,
    DatasetLocationStatus,
    DimensionRecordStatus,
    UnknownDataset,
)
from lsst.prompt_publication_service.test_utils import (
    create_butler_repo,
    create_publication_state_db,
    load_base_dimension_data,
    load_visit_dimension_data,
    register_test_dataset_types,
    EXPOSURE1,
    EXPOSURE2,
    VISIT1,
    VISIT2,
    VISIT_DATASET_TYPE,
    NONVISIT_DATASET_TYPE,
    EXPOSURE_DATASET_TYPE,
)


class TestRegistration(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        repo = self.enterContext(create_butler_repo())
        self.butler = self.enterContext(Butler.from_config(repo, run="run"))
        load_base_dimension_data(self.butler)
        load_visit_dimension_data(self.butler)
        register_test_dataset_types(self.butler)

    async def asyncSetUp(self) -> None:
        self.db = await self.enterAsyncContext(create_publication_state_db())

    async def test_register_datasets(self) -> None:
        pvi1 = self.butler.put(10, VISIT_DATASET_TYPE, instrument="LSSTCam", visit=VISIT1.id, detector=10)
        pvi2 = self.butler.put(11, VISIT_DATASET_TYPE, instrument="LSSTCam", visit=VISIT2.id, detector=11)
        rti = self.butler.put(
            2, NONVISIT_DATASET_TYPE, instrument="LSSTCam", detector=10, group="2025-12-03T07:58:25.583"
        )
        exposure_dataset1 = self.butler.put(
            10, EXPOSURE_DATASET_TYPE, instrument="LSSTCam", exposure=EXPOSURE1.id, detector=10
        )
        exposure_dataset2 = self.butler.put(
            11, EXPOSURE_DATASET_TYPE, instrument="LSSTCam", exposure=EXPOSURE2.id, detector=10
        )

        batch_data = {
            "batch_id": "59643df0-e0ed-445c-9fbe-417b526eab6b",
            "datasets": [
                *(str(ref.id) for ref in [pvi1, pvi2, rti, exposure_dataset1, exposure_dataset2]),
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
            with capture_logs() as logs:
                await register_dataset_batch_file(
                    self.db, DatasetOrigin.PROMPT_PROCESSING, self.butler, batch_file
                )
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0]["log_level"], "warning")
            self.assertIn("f3b0055f-7375-4154-b1e4-922656c0af44", logs[0]["missing_ids"])

        async def check_datasets() -> None:
            async with self.db.session() as session:
                datasets = list(await session.scalars(select(Dataset)))
                self.assertEqual(len(datasets), 5)
                visit_datasets = [d for d in datasets if d.dataset_type == VISIT_DATASET_TYPE]
                visit_datasets.sort(key=lambda d: d.visit)
                nonvisit_datasets = [d for d in datasets if d.dataset_type == NONVISIT_DATASET_TYPE]
                exposure_datasets = [d for d in datasets if d.dataset_type == EXPOSURE_DATASET_TYPE]
                exposure_datasets.sort(key=lambda d: d.exposure)

            self.assertEqual(len(visit_datasets), 2)
            self.assertEqual(visit_datasets[0].id, pvi1.id)
            self.assertIs(visit_datasets[0].origin, DatasetOrigin.PROMPT_PROCESSING)
            self.assertEqual(visit_datasets[0].dataset_type, "preliminary_visit_image")
            self.assertEqual(visit_datasets[0].instrument, "LSSTCam")
            self.assertEqual(visit_datasets[0].visit, VISIT1.id)
            self.assertIsNone(visit_datasets[0].exposure)
            self.assertEqual(visit_datasets[0].butler_data_id, {"detector": 10})
            self.assertIs(visit_datasets[0].embargo_status, DatasetLocationStatus.PRESENT)
            self.assertIs(visit_datasets[0].prompt_prep_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(visit_datasets[0].repo_main_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(visit_datasets[0].google_int_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(visit_datasets[0].google_prod_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIsNone(visit_datasets[0].unembargo_time)

            self.assertEqual(visit_datasets[1].id, pvi2.id)
            self.assertIs(visit_datasets[1].origin, DatasetOrigin.PROMPT_PROCESSING)
            self.assertEqual(visit_datasets[1].dataset_type, "preliminary_visit_image")
            self.assertEqual(visit_datasets[1].instrument, "LSSTCam")
            self.assertEqual(visit_datasets[1].visit, VISIT2.id)
            self.assertIsNone(visit_datasets[1].exposure)
            self.assertEqual(visit_datasets[1].butler_data_id, {"detector": 11})
            self.assertIs(visit_datasets[1].embargo_status, DatasetLocationStatus.PRESENT)
            self.assertIs(visit_datasets[1].prompt_prep_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(visit_datasets[1].repo_main_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(visit_datasets[1].google_int_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(visit_datasets[1].google_prod_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIsNone(visit_datasets[1].unembargo_time)

            self.assertEqual(len(nonvisit_datasets), 1)
            self.assertEqual(nonvisit_datasets[0].id, rti.id)
            self.assertEqual(nonvisit_datasets[0].origin, DatasetOrigin.PROMPT_PROCESSING)
            self.assertEqual(nonvisit_datasets[0].dataset_type, NONVISIT_DATASET_TYPE)
            self.assertEqual(nonvisit_datasets[0].instrument, "LSSTCam")
            self.assertIsNone(nonvisit_datasets[0].visit)
            self.assertIsNone(nonvisit_datasets[0].exposure)
            self.assertEqual(nonvisit_datasets[0].butler_data_id, {"detector": 10})
            self.assertIs(nonvisit_datasets[0].embargo_status, DatasetLocationStatus.PRESENT)
            self.assertIs(nonvisit_datasets[0].prompt_prep_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(nonvisit_datasets[0].repo_main_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(nonvisit_datasets[0].google_int_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(nonvisit_datasets[0].google_prod_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIsNone(nonvisit_datasets[0].unembargo_time)

            self.assertEqual(len(exposure_datasets), 2)
            self.assertEqual(exposure_datasets[0].id, exposure_dataset1.id)
            self.assertEqual(exposure_datasets[0].origin, DatasetOrigin.PROMPT_PROCESSING)
            self.assertEqual(exposure_datasets[0].dataset_type, EXPOSURE_DATASET_TYPE)
            self.assertEqual(exposure_datasets[0].instrument, "LSSTCam")
            self.assertIsNone(exposure_datasets[0].visit)
            self.assertEqual(exposure_datasets[0].exposure, EXPOSURE1.id)
            self.assertEqual(exposure_datasets[0].butler_data_id, {"detector": 10})
            self.assertIs(exposure_datasets[0].embargo_status, DatasetLocationStatus.PRESENT)
            self.assertIs(exposure_datasets[0].prompt_prep_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(exposure_datasets[0].repo_main_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(exposure_datasets[0].google_int_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(exposure_datasets[0].google_prod_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIsNone(exposure_datasets[0].unembargo_time)

            self.assertEqual(exposure_datasets[1].id, exposure_dataset2.id)
            self.assertEqual(exposure_datasets[1].origin, DatasetOrigin.PROMPT_PROCESSING)
            self.assertEqual(exposure_datasets[1].dataset_type, EXPOSURE_DATASET_TYPE)
            self.assertEqual(exposure_datasets[1].instrument, "LSSTCam")
            self.assertIsNone(exposure_datasets[1].visit)
            self.assertEqual(exposure_datasets[1].exposure, EXPOSURE2.id)
            self.assertEqual(exposure_datasets[1].butler_data_id, {"detector": 10})
            self.assertIs(exposure_datasets[1].embargo_status, DatasetLocationStatus.PRESENT)
            self.assertIs(exposure_datasets[1].prompt_prep_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(exposure_datasets[1].repo_main_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(exposure_datasets[1].google_int_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIs(exposure_datasets[1].google_prod_status, DatasetLocationStatus.NEVER_PRESENT)
            self.assertIsNone(exposure_datasets[1].unembargo_time)

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
            visits.sort(key=lambda visit: visit.id)

        def _assert_initial_dimension_status_values(row: Visit | Exposure) -> None:
            self.assertIs(row.embargo_status, DimensionRecordStatus.INITIAL)
            self.assertIs(row.prompt_prep_status, DimensionRecordStatus.NEVER_PRESENT)
            self.assertIs(row.repo_main_status, DimensionRecordStatus.NEVER_PRESENT)
            self.assertIs(row.google_int_status, DimensionRecordStatus.NEVER_PRESENT)
            self.assertIs(row.google_prod_status, DimensionRecordStatus.NEVER_PRESENT)

        self.assertEqual(len(visits), 2)

        self.assertEqual(visits[0].id, VISIT1.id)
        self.assertEqual(visits[0].instrument, "LSSTCam")
        self.assertEqual(visits[0].day_obs, 20251202)
        self.assertEqual(visits[0].time, VISIT1.time)
        _assert_initial_dimension_status_values(visits[0])

        self.assertEqual(visits[1].id, VISIT2.id)
        self.assertEqual(visits[1].instrument, "LSSTCam")
        self.assertEqual(visits[0].day_obs, 20251202)
        self.assertEqual(visits[1].time, VISIT2.time)
        _assert_initial_dimension_status_values(visits[1])

        async with self.db.session() as session:
            exposures = list(await session.scalars(select(Exposure)))
            exposures.sort(key=lambda exposure: exposure.id)

        self.assertEqual(len(exposures), 2)

        self.assertEqual(exposures[0].id, EXPOSURE1.id)
        self.assertEqual(exposures[0].instrument, "LSSTCam")
        self.assertEqual(exposures[0].day_obs, 20251202)
        self.assertEqual(exposures[0].time, EXPOSURE1.time)
        self.assertTrue(exposures[0].can_see_sky)
        _assert_initial_dimension_status_values(exposures[0])

        self.assertEqual(exposures[1].id, EXPOSURE2.id)
        self.assertEqual(exposures[1].instrument, "LSSTCam")
        self.assertEqual(exposures[1].day_obs, 20251202)
        self.assertEqual(exposures[1].time, EXPOSURE2.time)
        # Note -- this checks an edge case where the input can_see_sky is null.
        self.assertTrue(exposures[1].can_see_sky)
        _assert_initial_dimension_status_values(exposures[1])

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
