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

import re
from typing import Any, Literal

from pydantic import BaseModel, field_validator


HEADER_NAME_RE = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")

#: headers a request item cannot set: they describe the connection or are set by the
#: reverse proxy, which applications may trust (client address, host, scheme)
FORBIDDEN_HEADERS = frozenset(
    {
        'host',
        'content-length',
        'transfer-encoding',
        'connection',
        'keep-alive',
        'upgrade',
        'expect',
        'te',
        'trailer',
        'forwarded',
        'x-forwarded-for',
        'x-forwarded-host',
        'x-forwarded-proto',
        'x-forwarded-port',
        'x-forwarded-prefix',
        'x-real-ip',
    }
)


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

    @field_validator('headers')
    @classmethod
    def headers_check(cls, value):
        if value is None:
            return value
        headers = []
        for name, header_value in value:
            name = str(name).lower()
            header_value = str(header_value)
            if not HEADER_NAME_RE.fullmatch(name):
                raise ValueError(f'invalid header name: {name!r}')
            if name in FORBIDDEN_HEADERS:
                raise ValueError(f'the header {name!r} cannot be set')
            if any(ch in header_value for ch in '\r\n\0'):
                raise ValueError(f'invalid value of the header {name!r}')
            try:
                header_value.encode('latin-1')
            except UnicodeEncodeError:
                raise ValueError(f'the value of the header {name!r} must be latin-1') from None
            headers.append((name, header_value))
        return headers


class BulkResponseItemSchema(BaseModel):
    endpoint: str
    status: int
    response: str | dict | list | None
    headers: list[tuple[str, Any]]
