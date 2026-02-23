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

from pydantic_settings import BaseSettings, SettingsConfigDict

from lsst.daf.butler import LabeledButlerFactory

from .configs.prompt_processing_outputs import PROMPT_PROCESSING_OUTPUT_CONFIG
from .database import Database
from .run_tasks import run_tasks
from .tasks.all import ALL_TASKS
from .tasks.base import TaskContext
from .tasks.impl.process_pool import initialize_worker_pool


class ServiceConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="promptpub_")

    state_database_uri: str
    embargo_repo_path: str
    main_repo_path: str
    prompt_prep_repo_path: str
    google_int_repo_path: str


async def main() -> None:
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
        async with Database(config.state_database_uri) as db:
            context = TaskContext(PROMPT_PROCESSING_OUTPUT_CONFIG, butler_factory, db, worker_pool)
            await run_tasks(context, ALL_TASKS)


if __name__ == "__main__":
    asyncio.run(main())
