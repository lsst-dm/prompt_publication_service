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

import asyncio

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from lsst.daf.butler import LabeledButlerFactory

from .configs.prompt_processing_outputs import PROMPT_PROCESSING_OUTPUT_CONFIG
from .database import Database
from .ingest.ingester import Ingester
from .ingest.kafka_reader import KafkaReader
from .run_tasks import run_tasks
from .tasks.all import ALL_TASKS
from .tasks.base import TaskContext
from .tasks.impl.process_pool import initialize_worker_pool


class ServiceConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="promptpub_")

    state_database_uri: str
    """SQLAlchemy connection URI for the Prompt Publication postgres
    database.
    """
    state_database_password: SecretStr | None = None
    """Password for the postgres database.  If not set, will be read
    from the Postgres password file.
    """
    embargo_repo_path: str
    """Path to the ``embargo`` Butler repository configuration file."""
    main_repo_path: str
    """Path to the ``/repo/main`` Butler repository configuration file."""
    prompt_prep_repo_path: str
    """Path to the ``prompt_prep`` Butler repository configuration file."""
    google_int_repo_path: str
    """Path to the ``prompt`` Butler repository configuration file for the
    Google integration test environment.
    """

    kafka_server: str
    """Kafka bootstrap server, as ``hostname:port``"""
    kafka_topic: str
    """Kafka topic that will be used to consume dataset batch messages."""
    kafka_group_id: str
    """Kafka consumer group ID that will be used to track read offsets.  Should
    be set once for a deployment and never changed -- otherwise the service
    will re-read topics from the beginning.
    """
    kafka_username: str
    """Username for connection to the Kafka cluster."""
    kafka_password: SecretStr
    """Password for connection to the Kafka cluster."""
    embargo_batch_file_directory: str
    """URI (in `lsst.resources.ResourcePath` format) to the directory where
    lists of ingested datasets are written by the Prompt Processing Butler
    Writer."""


async def main() -> None:
    """Top-level service application for prompt publication."""

    config = ServiceConfig()

    repositories = {
        "embargo": config.embargo_repo_path,
        "prompt_prep": config.prompt_prep_repo_path,
        "/repo/main": config.main_repo_path,
        "prompt_google_int": config.google_int_repo_path,
    }

    with (
        LabeledButlerFactory(
            repositories,
            writeable=True,
        ) as butler_factory,
        initialize_worker_pool(repositories) as worker_pool,
    ):
        db_password = (
            None
            if config.state_database_password is None
            else config.state_database_password.get_secret_value()
        )
        async with (
            Database(config.state_database_uri, password=db_password) as state_db,
            asyncio.TaskGroup() as tg,
        ):
            context = TaskContext(PROMPT_PROCESSING_OUTPUT_CONFIG, butler_factory, state_db, worker_pool)
            tg.create_task(run_tasks(context, ALL_TASKS))
            tg.create_task(_ingest_from_kafka(config, state_db, butler_factory))


async def _ingest_from_kafka(
    config: ServiceConfig, state_db: Database, butler_factory: LabeledButlerFactory
) -> None:
    """Background task that reads list of datasets from Kafka and
    ingests them in the state database.
    """
    async with (
        KafkaReader(
            bootstrap_servers=config.kafka_server,
            topic=config.kafka_topic,
            group_id=config.kafka_group_id,
            username=config.kafka_username,
            password=config.kafka_password.get_secret_value(),
        ) as kafka,
    ):
        butler = await asyncio.to_thread(butler_factory.create_butler, "embargo")
        try:
            ingester = Ingester(kafka, state_db, butler, config.embargo_batch_file_directory)
            while True:
                await ingester.process_one()
        finally:
            await asyncio.to_thread(butler.close)


if __name__ == "__main__":
    asyncio.run(main())
