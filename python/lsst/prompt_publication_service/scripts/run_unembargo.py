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

from ..configs.prompt_processing_outputs import PROMPT_PROCESSING_OUTPUT_CONFIG
from ..database import Database
from ..tasks.transfer import unembargo_datasets


@click.command()
@click.argument("database_uri")
@click.argument("source_butler_repo")
@click.argument("target_butler_repo")
def run_unembargo(database_uri: str, source_butler_repo: str, target_butler_repo: str) -> None:
    source_butler = Butler.from_config(source_butler_repo)
    target_butler = Butler.from_config(target_butler_repo)
    asyncio.run(_run(database_uri, source_butler, target_butler))


async def _run(database_uri: str, source_butler: Butler, target_butler: Butler) -> None:
    async with Database(database_uri) as db:
        await unembargo_datasets(PROMPT_PROCESSING_OUTPUT_CONFIG, source_butler, target_butler, db)


if __name__ == "__main__":
    run_unembargo()
