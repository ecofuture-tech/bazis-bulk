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
import dataclasses
import functools
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import ContextVar, copy_context

from django.db import connections, transaction

import anyio
import anyio.to_thread
from asgiref.sync import sync_to_async


@dataclasses.dataclass
class _DedicatedThread:
    executor: ThreadPoolExecutor
    #: the event loop of the bulk request
    loop: asyncio.AbstractEventLoop
    thread_ident: int | None = None
    active: bool = True


#: the dedicated thread of the atomic bulk request running in the current context
_dedicated_thread: ContextVar[_DedicatedThread | None] = ContextVar(
    'bulk_dedicated_thread', default=None
)
#: set while any bulk request (atomic or not) runs in the current context
_in_bulk: ContextVar[bool] = ContextVar('bulk_in_bulk', default=False)


def _run_sync_wrapper(run_sync):
    @functools.wraps(run_sync)
    async def wrapper(func, *args, **kwargs):
        dedicated = _dedicated_thread.get()
        # outside of an atomic bulk request, or in a task that outlived it
        if dedicated is None or not dedicated.active:
            return await run_sync(func, *args, **kwargs)

        if asyncio.get_running_loop() is not dedicated.loop:
            # the code of the dedicated thread started an event loop of its own: the
            # dedicated thread waits for it, so a call queued to its executor would never run
            if threading.get_ident() == dedicated.thread_ident:
                # the loop runs in the dedicated thread itself (asyncio.run)
                return func(*args)
            # async_to_sync (e.g. RouteBase.raw_call) runs the loop in another thread;
            # asgiref runs thread-sensitive calls in the thread that called async_to_sync
            return await sync_to_async(func, thread_sensitive=True)(*args)

        context = copy_context()
        return await dedicated.loop.run_in_executor(
            dedicated.executor, functools.partial(context.run, func, *args)
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
    return _in_bulk.get()


def set_in_bulk_request():
    """
    Marks the current context (the bulk request and everything it calls) as a bulk request.
    Returns the token for `reset_in_bulk_request`.
    """
    return _in_bulk.set(True)


def reset_in_bulk_request(token):
    _in_bulk.reset(token)


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
        self.dedicated: _DedicatedThread | None = None
        self.dedicated_token = None

    async def _run(self, func, *args):
        return await asyncio.get_running_loop().run_in_executor(
            self.dedicated.executor, func, *args
        )

    def _transaction_start(self):
        self.dedicated.thread_ident = threading.get_ident()
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
        self.dedicated = _DedicatedThread(
            executor=ThreadPoolExecutor(max_workers=1, thread_name_prefix='bazis-bulk'),
            loop=asyncio.get_running_loop(),
        )
        try:
            await self._run(self._transaction_start)
        except BaseException:
            self.dedicated.executor.shutdown(wait=False)
            raise
        self.dedicated_token = _dedicated_thread.set(self.dedicated)
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        _dedicated_thread.reset(self.dedicated_token)
        # tasks started by the sub-requests may outlive the request: they must not use
        # the executor any more
        self.dedicated.active = False

        # the transaction must be finished even if the request is cancelled: the end is
        # queued after the running sub-request (if it was abandoned) and awaited until done,
        # shielded from the cancel scopes of anyio (which repeat the cancellation) and from
        # a plain cancellation of the task (asyncio.shield keeps the end in the queue)
        end: Future = self.dedicated.executor.submit(
            self._transaction_end, exc_type, exc_value, traceback
        )
        self.dedicated.executor.shutdown(wait=False)
        waiter = asyncio.wrap_future(end)
        cancelled: asyncio.CancelledError | None = None
        while not waiter.done():
            try:
                with anyio.CancelScope(shield=True):
                    await asyncio.shield(waiter)
            except asyncio.CancelledError as exc:
                cancelled = exc
        if cancelled is not None:
            # the original exception, so that the cancel scope that sent it recognizes it
            raise cancelled
        waiter.result()
