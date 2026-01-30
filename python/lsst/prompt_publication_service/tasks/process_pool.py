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
from collections.abc import Iterator, Callable
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
import multiprocessing
from typing import Concatenate

from lsst.daf.butler import LabeledButlerFactory


@contextmanager
def initialize_worker_pool(butler_repos: dict[str, str]) -> Iterator[WorkerPool]:
    with ProcessPoolExecutor(
        initializer=_initialize_process_pool_context,
        initargs=(butler_repos,),
        mp_context=multiprocessing.get_context("spawn"),
    ) as executor:
        yield WorkerPool(executor)


@dataclass(frozen=True)
class WorkerTaskContext:
    butler_factory: LabeledButlerFactory


type WorkerFunction[**_P, _T] = Callable[Concatenate[WorkerTaskContext, _P], _T]


class WorkerPool:
    def __init__(self, executor: ProcessPoolExecutor):
        self._executor = executor

    async def run[**_P, _T](self, func: WorkerFunction[_P, _T], *args: _P.args, **kwargs: _P.kwargs) -> _T:
        """Run the given function in a process pool.  The function must be
        pickleable (usually, a plain module-level function with a name). All
        arguments and the return value must also be pickleable.
        """
        if args:
            # Can be fixed after Python 3.14 by using 'functools.Placeholder' in partial.
            raise AssertionError("Specify all arguments to WorkerPool.run() as keyword args")
        func = partial(func, **kwargs)

        return await asyncio.get_running_loop().run_in_executor(self._executor, _run_worker_func, func)


_WORKER_TASK_CONTEXT: WorkerTaskContext | None = None


def _initialize_process_pool_context(butler_repos: dict[str, str]) -> None:
    global _WORKER_TASK_CONTEXT
    _WORKER_TASK_CONTEXT = WorkerTaskContext(
        butler_factory=LabeledButlerFactory(butler_repos, writeable=True)
    )


def _run_worker_func[_T](func: Callable[[WorkerTaskContext], _T]) -> _T:
    global _WORKER_TASK_CONTEXT
    context = _WORKER_TASK_CONTEXT
    if context is None:
        raise AssertionError("Worker process context was not initialized")
    return func(context)
