from bazis.core.app import app

from .routes import router  # noqa: F401
from .utils import threadpool_vars_prepare


class ThreadpoolVarsPrepareMiddleware:
    """
    The middleware calls the initializing function for the context variables of worker threads
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        threadpool_vars_prepare()
        await self.app(scope, receive, send)


app.add_middleware(ThreadpoolVarsPrepareMiddleware)
