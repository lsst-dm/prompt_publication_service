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

from __future__ import annotations

import asyncio
import multiprocessing
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from typing import Concatenate

from structlog.stdlib import BoundLogger

from lsst.daf.butler import LabeledButlerFactory

from ..logging import get_logger


@contextmanager
def initialize_worker_pool(butler_repos: dict[str, str]) -> Iterator[WorkerPool]:
    with ProcessPoolExecutor(
        initializer=WorkerPool._initialize_process_pool_context,
        initargs=(butler_repos,),
        mp_context=multiprocessing.get_context("spawn"),
    ) as executor:
        yield WorkerPool(executor)


@dataclass(frozen=True)
class WorkerTaskContext:
    butler_factory: LabeledButlerFactory
    log: BoundLogger


type WorkerFunction[**P, T] = Callable[Concatenate[WorkerTaskContext, P], T]


class WorkerPool:
    _WORKER_TASK_CONTEXT: WorkerTaskContext | None = None

    def __init__(self, executor: ProcessPoolExecutor):
        self._executor = executor

    async def run[**P, T](self, func: WorkerFunction[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        """Run the given function in a process pool.  The function must be
        pickleable (usually, a plain module-level function with a name). All
        arguments and the return value must also be pickleable.
        """
        if args:
            # Can be fixed after Python 3.14 by using 'functools.Placeholder' in partial.
            raise AssertionError("Specify all arguments to WorkerPool.run() as keyword args")
        func = partial(func, **kwargs)

        return await asyncio.get_running_loop().run_in_executor(
            self._executor, WorkerPool._run_worker_func, func
        )

    @classmethod
    def _initialize_process_pool_context(cls, butler_repos: dict[str, str]) -> None:
        cls._WORKER_TASK_CONTEXT = WorkerTaskContext(
            butler_factory=LabeledButlerFactory(butler_repos, writeable=True), log=get_logger()
        )

    @classmethod
    def _run_worker_func[T](cls, func: Callable[[WorkerTaskContext], T]) -> T:
        if cls._WORKER_TASK_CONTEXT is None:
            raise AssertionError("Worker process context was not initialized")
        return func(cls._WORKER_TASK_CONTEXT)
