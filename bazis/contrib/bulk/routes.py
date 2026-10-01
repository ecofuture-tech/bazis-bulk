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

import asyncio
import json
import logging
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.utils.translation import gettext_lazy as _

from fastapi import Request, Response

from bazis.core.errors import JsonApiBazisError, JsonApiBazisException
from bazis.core.routing import BazisRouter

from . import schemas
from .utils import (
    ThreadDedicated,
    ThreadsPool,
    in_bulk_request,
    reset_in_bulk_request,
    set_in_bulk_request,
)


logger = logging.getLogger(__name__)

router = BazisRouter(tags=[_('Bulk requests')])

#: the keys of the bulk request scope passed on to the sub-requests
SCOPE_KEYS = ('type', 'asgi', 'http_version', 'server', 'client', 'scheme', 'root_path', 'state')
#: the headers of the bulk request that do not apply to a sub-request
SKIPPED_HEADERS = {b'content-length', b'content-type', b'transfer-encoding', b'expect'}


class BulkRollbackError(Exception): ...


def _bulk_error(detail) -> JsonApiBazisException:
    return JsonApiBazisException(
        JsonApiBazisError(
            detail=str(detail), loc=('body',), code='ERR_BULK', title=_('Invalid bulk request'), status=400
        ),
        status=400,
    )


def _sub_request_scope(request: Request, item: schemas.BulkRequestItemSchema, body: bytes) -> dict:
    url = urlsplit(item.endpoint)
    headers = {
        name: value for name, value in request.scope['headers'] if name not in SKIPPED_HEADERS
    }
    headers[b'content-type'] = b'application/vnd.api+json'
    for name, value in item.headers or ():
        headers[name.encode('latin-1')] = value.encode('latin-1')
    headers[b'content-length'] = str(len(body)).encode()

    scope = {key: request.scope[key] for key in SCOPE_KEYS if key in request.scope}
    if 'state' in scope:
        scope['state'] = scope['state'].copy()
    scope.update(
        {
            'method': item.method,
            'path': unquote(url.path),
            'raw_path': url.path.encode(),
            'query_string': url.query.encode(),
            'headers': list(headers.items()),
        }
    )
    return scope


async def _run_sub_request(app, scope: dict, body: bytes, result: dict):
    body_sent = False

    async def receive():
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {'type': 'http.request', 'body': body, 'more_body': False}
        # the client of a sub-request never disconnects: wait until the application stops
        # listening (e.g. a streaming response finished) instead of answering in a loop
        await asyncio.Event().wait()

    body_parts = []

    async def send(message):
        if message['type'] == 'http.response.start':
            result['status'] = message['status']
            result['headers'] = message.get('headers', [])
        elif message['type'] == 'http.response.body':
            body_parts.append(message.get('body', b''))

    try:
        await app(scope, receive, send)
    except Exception:
        # the error middleware has already sent the 500 response if it could
        logger.exception('Bulk: the sub-request %s %s failed', scope['method'], scope['path'])
        result.setdefault('status', 500)
        result.setdefault('headers', [])

    response_body = b''.join(body_parts)
    content_type = dict(result['headers']).get(b'content-type', b'')
    if b'json' in content_type:
        result['response'] = json.loads(response_body) if response_body else None
    else:
        result['response'] = response_body.decode('utf-8', errors='replace') or None


@router.post('/bulk/', response_model=list[schemas.BulkResponseItemSchema])
async def bulk(
    request: Request,
    response: Response,
    items: list[schemas.BulkRequestItemSchema],
    is_atomic: bool = True,
):
    """
    Executes the requests of the list one after another and returns their responses.

    With `is_atomic=true` (default) all requests run in one database transaction, which is
    rolled back, and the response status is 400, if any of them fails (status >= 400).
    With `is_atomic=false` every request runs in its own transaction.
    """
    from bazis.core.app import app

    if in_bulk_request():
        raise _bulk_error(_('A bulk request cannot contain bulk requests'))
    if len(items) > settings.BAZIS_BULK_MAX_ITEMS:
        raise _bulk_error(
            _('A bulk request can contain at most %(limit)s requests')
            % {'limit': settings.BAZIS_BULK_MAX_ITEMS}
        )

    results = []
    response.status_code = 200
    thread_behavior = ThreadDedicated() if is_atomic else ThreadsPool()
    in_bulk_token = set_in_bulk_request()

    try:
        async with thread_behavior as thread:
            for item in items:
                body = (
                    b''
                    if item.body is None
                    else json.dumps(item.body, ensure_ascii=False, allow_nan=False).encode()
                )
                result = {'endpoint': item.endpoint}
                await _run_sub_request(app, _sub_request_scope(request, item, body), body, result)
                # a failed sub-request breaks the transaction: start a new one for the next
                await thread.check()

                if is_atomic and result['status'] >= 400:
                    response.status_code = 400
                results.append(result)

            if response.status_code >= 400:
                raise BulkRollbackError
    except BulkRollbackError:
        pass
    finally:
        reset_in_bulk_request(in_bulk_token)

    return results
