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

from __future__ import annotations

from typing import Literal
from uuid import UUID

from lsst.daf.butler import Butler
from lsst.resources import ResourcePath
import pydantic

from ..database import Database
from ..register import register_dataset_batch_file
from ..schema import DatasetOrigin
from .kafka_reader import KafkaReader


class _BatchIngestedEvent(pydantic.BaseModel):
    """Kafka message sent from Butler Writer Service to Prompt Publication
    Service, signaling that new datasets have been ingested and can be
    considered for future un-embargo.
    """

    type: Literal["batch-ingested"]
    batch_id: UUID
    """Identifier for this batch of datasets."""
    origin: str
    """The name of the service that these datasets originated from."""
    batch_file: str
    """Path to file containing JSON-serialized version of `DatasetBatch`
    model.
    """


class Ingester:
    """Reads list of datasets from a Kafka topic and registers them in the
    state database.
    """

    def __init__(
        self, kafka: KafkaReader, state_db: Database, butler: Butler, batch_file_directory: str
    ) -> None:
        self._kafka = kafka
        self._state_db = state_db
        self._butler = butler
        self._batch_file_directory = ResourcePath(batch_file_directory, forceDirectory=True)

    async def process_one(self) -> None:
        async with self._kafka.read_next_message_and_commit_on_success() as raw_message:
            message = _BatchIngestedEvent.model_validate_json(raw_message)
            batch_file = self._batch_file_directory.join(message.batch_file, forceDirectory=False)
            await register_dataset_batch_file(
                db=self._state_db,
                origin=_get_origin(message),
                source_butler=self._butler,
                batch_file=batch_file,
            )


def _get_origin(message: _BatchIngestedEvent) -> DatasetOrigin:
    if message.origin == "prompt_processing":
        return DatasetOrigin.PROMPT_PROCESSING

    raise ValueError(f"Unknown dataset origin '{message.origin}' in batch file '{message.batch_file}'")
