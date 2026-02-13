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

import datetime
import tempfile
from collections.abc import AsyncIterator, Iterable, Iterator
from contextlib import AsyncExitStack, ExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path

from lsst.daf.butler import Butler, Config, DatasetType, LabeledButlerFactory

from .configs.prompt_processing_outputs import PROMPT_PROCESSING_OUTPUT_CONFIG
from .database import Database
from .schema import ButlerRepository
from .tasks.base import TaskContext
from .tasks.impl.process_pool import initialize_worker_pool


@contextmanager
def create_empty_butler_repo() -> Iterator[str]:
    """Create an empty Butler repository."""
    with tempfile.TemporaryDirectory() as temp_dir:
        Butler.makeRepo(temp_dir)
        yield temp_dir


@contextmanager
def create_butler_repo_with_shared_datastore(shared_datastore_path: str) -> Iterator[str]:
    """Create a Butler repository that shares a datastore directory with
    another repository, but has its own independent database.

    Notes
    -----
    This is meant to simulate the configuration of the Google ``prompt`` repos,
    which access the files stored in the `prompt_prep` repo via S3.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        config = Config()
        config["datastore", "datastore", "root"] = shared_datastore_path
        # Match default value from the Butler configuration for the original datastore
        config["datastore", "datastore", "name"] = "FileDatastore@<butlerRoot>"
        Butler.makeRepo(temp_dir, config, forceConfigRoot=False)
        yield temp_dir


@contextmanager
def create_butler(run: str) -> Iterator[Butler]:
    with create_empty_butler_repo() as repo:
        with Butler.from_config(repo, writeable=True, run=run) as butler:
            yield butler


@asynccontextmanager
async def create_publication_state_db() -> AsyncIterator[Database]:
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_path = Path(temp_dir) / "publication_state.sqlite"
        async with Database(f"sqlite+aiosqlite:///{str(sqlite_path)}") as db:
            await db.initialize_tables()
            yield db


def get_path_to_test_data_file(filename: str) -> str:
    data_dir = Path(__file__).absolute().parent.parent.parent.parent / "tests" / "data"
    return str(data_dir / filename)


def load_base_dimension_data(butler: Butler) -> None:
    butler.import_(filename=get_path_to_test_data_file("base_dimensions.yaml"))


def load_visit_dimension_data(butler: Butler) -> None:
    butler.import_(filename=get_path_to_test_data_file("visit_dimensions.yaml"))


VISIT_DATASET_TYPE = "preliminary_visit_image"
UNPUBLISHED_VISIT_DATASET_TYPE = "template_detector"
NONVISIT_DATASET_TYPE = "regionTimeInfo"
EXPOSURE_DATASET_TYPE = "isr_log"


@dataclass(frozen=True)
class TestVisitOrExposure:
    id: int
    time: datetime.datetime


VISIT1 = TestVisitOrExposure(2025120200439, datetime.datetime(2025, 12, 3, 7, 59, 1, 355000))
VISIT2 = TestVisitOrExposure(2025120200440, datetime.datetime(2025, 12, 3, 8, 0, 27, 811000))
# At present, exposures usually have the same IDs and some other data as their
# corresponding visits.
# However, it is possible to have an exposure for which no corresponding visit
# exists.
EXPOSURE1 = VISIT1
EXPOSURE2 = VISIT2


def register_test_dataset_types(butler: Butler) -> None:
    # Register a dataset type with a 'visit' dimension that will be published
    # to Google.
    butler.registry.registerDatasetType(
        DatasetType(VISIT_DATASET_TYPE, butler.dimensions.conform(["visit", "detector"]), "int")
    )
    # Register a dataset type with a visit dimension that will not be published
    # to Google.
    butler.registry.registerDatasetType(
        DatasetType(UNPUBLISHED_VISIT_DATASET_TYPE, butler.dimensions.conform(["visit", "detector"]), "int")
    )
    # One with an exposure dimension, that will be published.
    butler.registry.registerDatasetType(
        DatasetType(
            EXPOSURE_DATASET_TYPE, butler.dimensions.conform(["instrument", "detector", "exposure"]), "int"
        ),
    )
    # And one with no visit or exposure dimensions.
    butler.registry.registerDatasetType(
        DatasetType(
            NONVISIT_DATASET_TYPE, butler.dimensions.conform(["instrument", "detector", "group"]), "int"
        )
    )


@contextmanager
def setup_butler_repos() -> Iterator[dict[str, str]]:
    repo_paths: dict[str, str] = {}
    with ExitStack() as exit_stack:
        for repo in ("embargo", "prompt_prep", "/repo/main"):
            repo_paths[repo] = exit_stack.enter_context(create_empty_butler_repo())
        repo_paths["prompt_google_int"] = exit_stack.enter_context(
            create_butler_repo_with_shared_datastore(repo_paths["prompt_prep"])
        )
        yield repo_paths


@asynccontextmanager
async def setup_task_context_with_empty_repos(
    repos: Iterable[ButlerRepository],
) -> AsyncIterator[TaskContext]:
    async with AsyncExitStack() as exit_stack:
        repo_paths = exit_stack.enter_context(setup_butler_repos())
        butler_factory = exit_stack.enter_context(LabeledButlerFactory(repo_paths, writeable=True))
        worker_pool = exit_stack.enter_context(initialize_worker_pool(repo_paths))
        state_database = await exit_stack.enter_async_context(create_publication_state_db())
        yield TaskContext(
            dataset_config=PROMPT_PROCESSING_OUTPUT_CONFIG,
            butler_factory=butler_factory,
            state_database=state_database,
            worker_pool=worker_pool,
        )
