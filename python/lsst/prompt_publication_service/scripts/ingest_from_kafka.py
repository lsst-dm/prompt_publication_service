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

import click

from lsst.daf.butler import Butler

from ..database import Database
from ..ingest.ingester import Ingester
from ..ingest.kafka_reader import KafkaReader


@click.command()
@click.option("--butler-repo", required=True, default="embargo")
@click.option("--database-uri", required=True)
@click.option("--kafka-server", required=True)
@click.option("--kafka-topic", default="butler-writer-ingestion-events")
@click.option("--kafka-group-id", required=True)
@click.option("--kafka-username", required=True)
@click.option("--batch-file-directory", required=True)
def register_datasets_from_kafka(
    butler_repo: str,
    database_uri: str,
    kafka_server: str,
    kafka_topic: str,
    kafka_group_id: str,
    kafka_username: str,
    batch_file_directory: str,
) -> None:
    kafka_password = click.prompt("Kafka password", hide_input=True)
    with Butler.from_config(butler_repo) as butler:

        async def run() -> None:
            async with (
                KafkaReader(
                    bootstrap_servers=kafka_server,
                    topic=kafka_topic,
                    group_id=kafka_group_id,
                    username=kafka_username,
                    password=kafka_password,
                ) as kafka,
                Database(database_uri) as state_db,
            ):
                ingester = Ingester(kafka, state_db, butler, batch_file_directory)
                while True:
                    await ingester.process_one()

        asyncio.run(run())


if __name__ == "__main__":
    register_datasets_from_kafka()
