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
