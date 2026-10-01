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

from typing import Any, Literal

from pydantic import BaseModel, field_validator


class BulkRequestItemSchema(BaseModel):
    endpoint: str
    method: Literal['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'] = 'GET'
    body: dict | list | None = None
    #: headers added to (or replacing) the headers of the bulk request
    headers: list[tuple[str, Any]] | None = None

    @field_validator('method', mode='before')
    @classmethod
    def method_upper(cls, value):
        return value.upper() if isinstance(value, str) else value


class BulkResponseItemSchema(BaseModel):
    endpoint: str
    status: int
    response: str | dict | list | None
    headers: list[tuple[str, Any]]
