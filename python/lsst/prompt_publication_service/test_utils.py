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
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager, asynccontextmanager
from dataclasses import dataclass
import datetime
from pathlib import Path

from lsst.daf.butler import Butler, DatasetType

from lsst.prompt_publication_service.database import Database


@contextmanager
def create_butler_repo(run: str | None = None) -> Iterator[Butler]:
    with tempfile.TemporaryDirectory() as temp_dir:
        Butler.makeRepo(temp_dir)
        with Butler.from_config(temp_dir, writeable=True, run=run) as butler:
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


def load_test_dimension_data(butler: Butler) -> None:
    butler.import_(filename=get_path_to_test_data_file("embargo_dimensions.yaml"))


VISIT_DATASET_TYPE = "preliminary_visit_image"
NONVISIT_DATASET_TYPE = "regionTimeInfo"


@dataclass(frozen=True)
class TestVisit:
    id: int
    time: datetime.datetime


VISIT1 = TestVisit(2025120200439, datetime.datetime(2025, 12, 3, 7, 59, 1, 355000))
VISIT2 = TestVisit(2025120200440, datetime.datetime(2025, 12, 3, 8, 0, 27, 811000))


def register_test_dataset_types(butler: Butler) -> None:
    # Register a dataset type with a 'visit' dimension...
    butler.registry.registerDatasetType(
        DatasetType(VISIT_DATASET_TYPE, butler.dimensions.conform(["visit", "detector"]), "int")
    )
    # And one without a visit dimension.
    butler.registry.registerDatasetType(
        DatasetType(
            NONVISIT_DATASET_TYPE, butler.dimensions.conform(["instrument", "detector", "group"]), "int"
        )
    )
