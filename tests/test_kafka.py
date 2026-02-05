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

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
import unittest.mock

from sqlalchemy import select

from lsst.prompt_publication_service.ingest.kafka_reader import KafkaReader
from lsst.prompt_publication_service.ingest.ingester import Ingester
from lsst.prompt_publication_service.schema import Dataset
from lsst.prompt_publication_service.test_utils import (
    VISIT1,
    VISIT_DATASET_TYPE,
    create_butler,
    create_publication_state_db,
    load_base_dimension_data,
    load_visit_dimension_data,
    register_test_dataset_types,
)


class TestKafkaIngest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.reader = KafkaReader(
            bootstrap_servers="test.invalid:9092",
            topic="a-topic",
            group_id="a-group-id",
            username="user",
            password="pass",
        )
        self.addAsyncCleanup(self.reader._consumer.stop)

    async def test_kafka_reader_happy_path(self) -> None:
        with unittest.mock.patch.object(self.reader, "_consumer", spec=True) as mock:
            async with self.reader:
                mock.start.assert_awaited()
                mock.getone.return_value = MockConsumerRecord("abc")
                async with self.reader.read_next_message_and_commit_on_success() as message:
                    self.assertEqual(message, "abc")
                    mock.commit.assert_not_called()
                mock.commit.assert_awaited()
            mock.stop.assert_awaited()

    async def test_kafka_reader_caller_exception(self) -> None:
        with unittest.mock.patch.object(self.reader, "_consumer", spec=True) as mock:
            async with self.reader:
                with self.assertRaisesRegex(RuntimeError, "this is the test exception"):
                    mock.getone.return_value = MockConsumerRecord("first")
                    async with self.reader.read_next_message_and_commit_on_success() as message:
                        self.assertEqual(message, "first")
                        raise RuntimeError("this is the test exception")
                mock.commit.assert_not_called()

                mock.reset_mock()
                # Simulate another message being available on the Kafka Topic.
                mock.getone.return_value = MockConsumerRecord("second")
                async with self.reader.read_next_message_and_commit_on_success() as message:
                    # Because the caller failed to process the message the
                    # first time, we get the original message again.
                    self.assertEqual(message, "first")
                mock.commit.assert_awaited()
                mock.reset_mock()
                async with self.reader.read_next_message_and_commit_on_success() as message:
                    self.assertEqual(message, "second")
                mock.commit.assert_awaited()

    async def test_ingester(self) -> None:
        db = await self.enterAsyncContext(create_publication_state_db())
        butler = self.enterContext(create_butler(run="run"))
        load_base_dimension_data(butler)
        load_visit_dimension_data(butler)
        register_test_dataset_types(butler)
        ref = butler.put(1, VISIT_DATASET_TYPE, instrument="LSSTCam", visit=VISIT1.id, detector=10)

        batch_directory = self.enterContext(TemporaryDirectory())
        batch_filename = "batch.json"
        batch_id = "db63fa2f-2cee-4b08-9f0f-2e1e3f218058"
        batch_data = {
            "batch_id": batch_id,
            "datasets": [str(ref.id)],
        }
        with open(Path(batch_directory) / batch_filename, "w", encoding="utf-8") as fh:
            json.dump(batch_data, fh)

        kafka_message_dict = {
            "type": "batch-ingested",
            "batch_id": batch_id,
            "origin": "prompt_processing",
            "batch_file": batch_filename,
        }
        kafka_message = json.dumps(kafka_message_dict)

        ingester = Ingester(self.reader, db, butler, f"file://{batch_directory}")
        with unittest.mock.patch.object(self.reader, "_consumer", spec=True) as mock:
            mock.getone.return_value = MockConsumerRecord(kafka_message)
            await ingester.process_one()

        async with db.session() as session:
            datasets = list(await session.scalars(select(Dataset)))
            self.assertEqual(len(datasets), 1)
            self.assertEqual(datasets[0].id, ref.id)
            self.assertEqual(datasets[0].dataset_type, VISIT_DATASET_TYPE)
            # Other fields are checked more thoroughly in
            # `test_state_database.py`.

        with self.assertRaisesRegex(ValueError, "Unknown dataset origin"):
            with unittest.mock.patch.object(self.reader, "_consumer", spec=True) as mock:
                kafka_message = json.dumps(kafka_message_dict | {"origin": "invalid"})
                mock.getone.return_value = MockConsumerRecord(kafka_message)
                await ingester.process_one()


class MockConsumerRecord:
    def __init__(self, value: str) -> None:
        self.value = value.encode("utf-8")
