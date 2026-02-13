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

from ..schema import Exposure, Group, Visit
from .base import Task
from .dimension_record_copy import DimensionRecordCopyTask
from .transfer import repo_main_transfer_task, unembargo_transfer_task

_DIMENSION_TABLES = (Visit, Group, Exposure)

ALL_TASKS: tuple[Task, ...] = (
    unembargo_transfer_task,
    repo_main_transfer_task,
    *(DimensionRecordCopyTask(table, "embargo", "prompt_prep") for table in _DIMENSION_TABLES),
    *(DimensionRecordCopyTask(table, "prompt_prep", "/repo/main") for table in _DIMENSION_TABLES),
)
