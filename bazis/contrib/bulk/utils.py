# Copyright 2026 EcoFuture Technology Services LLC and contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Execution of the sub-requests of an atomic bulk request in one dedicated thread.

FastAPI runs synchronous endpoints and dependencies in worker threads through
`anyio.to_thread.run_sync`. The sub-requests of an atomic bulk request must share one
database transaction, and a Django transaction belongs to the thread that opened it, so
all of them must run in the same thread. `ThreadDedicated` opens the transaction in a
thread of its own and, while it is active in the current context, `run_sync` sends the
synchronous calls of the sub-requests to that thread instead of the shared pool.
"""

import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context

from django.db import close_old_connections, connections, transaction

import anyio.to_thread


#: the executor of the dedicated thread of the bulk request running in the current context
_dedicated_executor: ContextVar[ThreadPoolExecutor | None] = ContextVar(
    'bulk_dedicated_executor', default=None
)


def _run_sync_wrapper(run_sync):
    @functools.wraps(run_sync)
    async def wrapper(func, *args, **kwargs):
        executor = _dedicated_executor.get()
        if executor is None:
            return await run_sync(func, *args, **kwargs)
        context = copy_context()
        return await asyncio.get_running_loop().run_in_executor(
            executor, functools.partial(context.run, func, *args)
        )

    wrapper.__bazis_bulk__ = True
    return wrapper


def install_run_sync_dispatch():
    """
    Wraps `anyio.to_thread.run_sync` once, so that it runs the calls made in the context
    of an atomic bulk request in its dedicated thread. Outside of a bulk request the
    wrapper calls the original function.
    """
    if not getattr(anyio.to_thread.run_sync, '__bazis_bulk__', False):
        anyio.to_thread.run_sync = _run_sync_wrapper(anyio.to_thread.run_sync)


def in_bulk_request() -> bool:
    return _dedicated_executor.get() is not None


class ThreadsPool:
    """
    Standard behavior: the sub-requests run in the shared thread pool, each in its own
    transaction.
    """

    async def check(self): ...

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback): ...


class ThreadDedicated(ThreadsPool):
    """
    Runs the sub-requests in one dedicated thread inside one transaction, which is
    committed when the context exits normally and rolled back when it exits with an
    exception.
    """

    def __init__(self, using=None):
        self.using = using
        self.atomic = transaction.atomic(using=using)
        self.executor: ThreadPoolExecutor | None = None
        self.executor_token = None

    async def _run(self, func, *args):
        return await asyncio.get_running_loop().run_in_executor(self.executor, func, *args)

    def _transaction_start(self):
        close_old_connections()
        self.atomic.__enter__()

    def _transaction_end(self, exc_type, exc_value, traceback):
        try:
            self.atomic.__exit__(exc_type, exc_value, traceback)
        finally:
            # the thread ends with the request: its connections would never be reused
            connections.close_all()

    def _transaction_restart_if_broken(self):
        # a failed sub-request marks the transaction for rollback: the following
        # sub-requests run in a new transaction, the request will be rolled back anyway
        if transaction.get_rollback(using=self.using):
            self.atomic.__exit__(None, None, None)
            self.atomic.__enter__()

    async def check(self):
        await self._run(self._transaction_restart_if_broken)

    async def __aenter__(self):
        install_run_sync_dispatch()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='bazis-bulk')
        try:
            await self._run(self._transaction_start)
        except BaseException:
            self.executor.shutdown(wait=False)
            raise
        self.executor_token = _dedicated_executor.set(self.executor)
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        _dedicated_executor.reset(self.executor_token)
        # the transaction must be finished even if the request is cancelled
        end = asyncio.ensure_future(
            self._run(self._transaction_end, exc_type, exc_value, traceback)
        )
        try:
            await asyncio.shield(end)
        except asyncio.CancelledError:
            await end
            raise
        finally:
            self.executor.shutdown(wait=False)
