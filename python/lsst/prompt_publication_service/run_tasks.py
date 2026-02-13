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
from collections.abc import Iterable

from .tasks.base import Task, TaskContext


async def run_tasks(context: TaskContext, tasks: Iterable[Task]) -> None:
    async with asyncio.TaskGroup() as tg:
        for task in tasks:
            tg.create_task(_run_single_task(context, task))


async def _run_single_task(context: TaskContext, task: Task) -> None:
    while True:
        result = await task.run(context)
        if result.result == "no-work-found":
            await asyncio.sleep(60)
