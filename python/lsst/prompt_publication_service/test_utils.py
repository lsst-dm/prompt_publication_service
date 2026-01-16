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

import tempfile
from collections.abc import AsyncIterator, Iterator, Iterable
from contextlib import contextmanager, asynccontextmanager, ExitStack
from dataclasses import dataclass
import datetime
from pathlib import Path

from lsst.daf.butler import Butler, DatasetType, LabeledButlerFactory

from .database import Database
from .schema import ButlerRepository


@contextmanager
def create_butler_repo() -> Iterator[str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        Butler.makeRepo(temp_dir)
        yield temp_dir


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


def load_test_dimension_data(butler: Butler) -> None:
    butler.import_(filename=get_path_to_test_data_file("embargo_dimensions.yaml"))


VISIT_DATASET_TYPE = "preliminary_visit_image"
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
    # Register a dataset type with a 'visit' dimension...
    butler.registry.registerDatasetType(
        DatasetType(VISIT_DATASET_TYPE, butler.dimensions.conform(["visit", "detector"]), "int")
    )
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
def setup_butler_factory_with_empty_repos(
    repos: Iterable[ButlerRepository],
) -> Iterator[LabeledButlerFactory]:
    with ExitStack() as exit_stack:
        repo_paths: dict[str, str] = {repo: exit_stack.enter_context(create_butler_repo()) for repo in repos}
        with LabeledButlerFactory(repo_paths, writeable=True) as factory:
            yield factory
