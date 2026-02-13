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

from lsst.daf.butler import ButlerRepoIndex, LabeledButlerFactory

from ..configs.prompt_processing_outputs import PROMPT_PROCESSING_OUTPUT_CONFIG
from ..database import Database
from ..run_tasks import run_tasks
from ..tasks.all import ALL_TASKS
from ..tasks.base import TaskContext
from ..tasks.process_pool import initialize_worker_pool
from ._utils import split_dataset_types_argument


@click.command()
@click.option("--database-uri", required=True)
@click.option("--embargo-repo", default="embargo")
@click.option("--main-repo", default="/repo/main")
@click.option("--prompt-prep-repo", default="prompt_prep")
@click.option("--types", default="")
def run_all_tasks(
    database_uri: str, embargo_repo: str, main_repo: str, prompt_prep_repo: str, types: str
) -> None:
    config = PROMPT_PROCESSING_OUTPUT_CONFIG
    if types:
        dataset_types = split_dataset_types_argument(types)
        config = config.subset(dataset_types)

    repositories = {
        "embargo": _lookup_butler_repo_path(embargo_repo),
        "prompt_prep": _lookup_butler_repo_path(prompt_prep_repo),
        "/repo/main": _lookup_butler_repo_path(main_repo),
    }

    with (
        LabeledButlerFactory(
            repositories,
            writeable=True,
        ) as butler_factory,
        initialize_worker_pool(repositories) as worker_pool,
    ):

        async def run():
            async with Database(database_uri) as db:
                context = TaskContext(config, butler_factory, db, worker_pool)
                await run_tasks(context, ALL_TASKS)

        asyncio.run(run())


def _lookup_butler_repo_path(repo_name_or_path: str) -> str:
    if repo_name_or_path in ButlerRepoIndex.get_known_repos():
        return str(ButlerRepoIndex.get_repo_uri(repo_name_or_path))
    else:
        return repo_name_or_path


if __name__ == "__main__":
    run_all_tasks()
