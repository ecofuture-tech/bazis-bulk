import asyncio
import sys
from collections import deque
from contextvars import ContextVar, copy_context
from typing import Any

from django.db import transaction

from anyio._backends._asyncio import (
    AsyncIOBackend,
    _threadpool_idle_workers,
    _threadpool_workers,
    find_root_task,
)
from anyio._backends._asyncio import WorkerThread as BaseWorkerThread
from sniffio import current_async_library_cvar


worker_dedicated = ContextVar('worker_dedicated')


# BaseWorkerThread_run = BaseWorkerThread.run
# def run_close_all(self) -> None:
#     """
#     We patch the synchronous task thread execution method so that connections are closed at the end of the thread's life,
#     created in this thread
#     """
#     try:
#         BaseWorkerThread_run(self)
#     finally:
#         connections.close_all()
# BaseWorkerThread.run = run_close_all


class IdleWorkersDeque(deque):
    """
    A patched double-ended queue that is oriented towards working with run_sync_in_worker_thread
    Bypasses limitations, allowing work only with a dedicated thread
    if it exists in the current execution context
    """

    def pop(self):
        try:
            return worker_dedicated.get()
        except LookupError:
            return super().pop()

    def __bool__(self):
        try:
            return bool(worker_dedicated.get())
        except LookupError:
            return bool(len(self))

    def __getitem__(self, *args):
        try:
            return worker_dedicated.get()
        except LookupError:
            return super().__getitem__(*args)


def threadpool_vars_prepare():
    """
    Patching environment service variables to enable working with a dedicated thread
    """
    try:
        _threadpool_idle_workers.get()
        _threadpool_workers.get()
    except LookupError:
        _threadpool_idle_workers.set(IdleWorkersDeque())
        _threadpool_workers.set(set())


class ThreadsPool:
    """
    Standard behavior of the thread pool
    """

    async def check(self): ...

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback): ...


class DedicatedWorkerThread(BaseWorkerThread):
    """
    In this implementation, idle_workers does not receive the current worker after executing a single task.
    In the native implementation, between tasks, a task from a neighboring context may slip in
    """

    def __init__(self, *args, **kwargs):
        pass
        super().__init__(*args, **kwargs)

    @property
    def idle_since(self):
        return AsyncIOBackend.current_time()

    @idle_since.setter
    def idle_since(self, value):
        pass

    def _report_result(
        self, future: asyncio.Future, result: Any, exc: BaseException | None
    ) -> None:
        if not future.cancelled():
            if exc is not None:
                future.set_exception(exc)
            else:
                future.set_result(result)

    def stop(self, f: asyncio.Task | None = None) -> None:
        self.stopping = True
        self.queue.put_nowait(None)


class ThreadDedicated(ThreadsPool):
    """
    FastApi executes synchronous routes inside a thread pool. However, if several synchronous routes need
    to be executed within a single transaction, then the thread must also be the same.
    This context manager sets up a custom dedicated thread
    in the low-level library anyio._backends._asyncio, in the method of which
    the route is executed: anyio._backends._asyncio.run_sync_in_worker_thread.
    Thus, the goal of executing all routes in a single transaction is achieved.
    """

    def __init__(self, using=None):
        self.atomic = transaction.atomic(using=using)
        self.worker = None
        self.worker_token = None

    def _transaction_start(self):
        self.atomic.__enter__()

    def _transaction_commit(self):
        self.atomic.__exit__(None, None, None)

    def _transaction_rollback(self, exc_type, exc_value, traceback):
        self.atomic.__exit__(exc_type, exc_value, traceback)

    def _transaction_clean_rollback(self):
        if transaction.get_rollback():
            self.atomic.__exit__(*sys.exc_info())
            self.atomic.__enter__()

    async def _task_push(self, func, *args):
        if self.worker:
            future: asyncio.Future = asyncio.Future()
            context = copy_context()
            self.worker.queue.put_nowait((context, func, args, future, None))
            await future

    async def check(self):
        await self._task_push(self._transaction_clean_rollback)

    async def __aenter__(self):
        current_async_library_cvar.set('asyncio')

        workers = _threadpool_workers.get()
        idle_workers = _threadpool_idle_workers.get()

        root_task = find_root_task()
        self.worker = DedicatedWorkerThread(root_task, workers, idle_workers)
        self.worker.start()
        self.worker_token = worker_dedicated.set(self.worker)

        await self._task_push(self._transaction_start)
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_type:
            await self._task_push(self._transaction_rollback, exc_type, exc_value, traceback)
        else:
            await self._task_push(self._transaction_commit)

        worker_dedicated.reset(self.worker_token)

        self.worker.stop()
