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
from collections import defaultdict
import re

import click
from lsst.daf.butler import Butler, DatasetRef

from ..database import Database
from ..register import register_embargo_datasets
from ..schema import DatasetOrigin


@click.command()
@click.argument("butler_repo")
@click.argument("database_uri")
@click.argument("collections", nargs=-1)
@click.option("--types", default="*")
def register_embargo_datasets_from_collections(
    butler_repo: str, database_uri: str, collections: tuple[str, ...], types: str
) -> None:
    """Script that adds datasets to the state database from a given collection
    in a Butler repository.
    """
    dataset_types = re.split(r"[\s,]+", types)
    with Butler.from_config(butler_repo) as butler:
        print("Searching for datasets")
        datasets = butler.query_all_datasets(collections, name=dataset_types, limit=None)
        dataset_counts: dict[str, int] = defaultdict(lambda: 0)
        for ref in datasets:
            dataset_counts[ref.datasetType.name] += 1
        print("Found datasets:")
        for dataset_type in sorted(dataset_counts.keys()):
            print(f"  {dataset_type}: {dataset_counts[dataset_type]}")
        if click.confirm("Register datasets?"):
            asyncio.run(_register_datasets(butler, database_uri, datasets))


async def _register_datasets(butler: Butler, database_uri: str, datasets: list[DatasetRef]) -> None:
    async with Database(database_uri) as db:
        await register_embargo_datasets(db, DatasetOrigin.PROMPT_PROCESSING, butler, datasets)


if __name__ == "__main__":
    register_embargo_datasets_from_collections()
