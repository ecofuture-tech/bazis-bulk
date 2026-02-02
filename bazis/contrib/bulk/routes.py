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

import json
from urllib.parse import urlparse

from django.utils.translation import gettext_lazy as _

from fastapi import Request, Response

from bazis.core.routing import BazisRouter

from . import schemas
from .utils import ThreadDedicated, ThreadsPool


router = BazisRouter(tags=[_('Bulk requests')])


class BulkRollbackError(Exception): ...


@router.post('/bulk/', response_model=list[schemas.BulkResponseItemSchema])
async def bulk(
    request: Request,
    response: Response,
    items: list[schemas.BulkRequestItemSchema],
    is_atomic: bool = True,
):
    from bazis.core.app import app

    # collect the list of responses
    results = []

    if is_atomic:
        thread_behavior = ThreadDedicated()
    else:
        thread_behavior = ThreadsPool()

    try:
        async with thread_behavior as thread:
            for item in items:  # type: schemas.BulkRequestItemSchema
                # parse the endpoint
                url = urlparse(item.endpoint)

                # build the scope
                scope = {
                    'type': request.scope.get('type'),
                    'asgi': request.scope.get('asgi'),
                    'http_version': request.scope.get('http_version'),
                    'server': request.scope.get('server'),
                    'client': request.scope.get('client'),
                    'scheme': request.scope.get('scheme'),
                    'headers': request.scope['headers'],
                    'method': item.method.upper(),
                    'query_string': url.query and url.query.encode(),
                    'path': url.path,
                    'raw_path': url.path,
                }

                # build the response
                result = {
                    'endpoint': item.endpoint,
                }

                async def receive(_item=item):
                    return {
                        'type': 'http.request',
                        'body': json.dumps(
                            _item.body,
                            ensure_ascii=False,
                            allow_nan=False,
                        ).encode("utf-8"),
                    }

                async def sender(_data, _result=result):
                    if _data['type'] == 'http.response.start':
                        _result['status'] = _data['status']
                        _result['headers'] = _data['headers']
                    if _data['type'] == 'http.response.body':
                        # determine the content type
                        content_type = dict(_result['headers']).get(b'content-type')
                        if content_type and b'json' in content_type:
                            _result['response'] = (
                                json.loads(_data['body']) if _data['body'] else None
                            )
                        else:
                            _result['response'] = _data['body']

                # run the route execution in a dedicated thread (since we are in the context of this thread)
                await app.__call__(scope, receive, sender)
                # if an exception occurred inside the dedicated thread - the transaction needs to be restarted
                await thread.check()

                # for any incorrect response of a package item - we make the overall package status non-working
                if is_atomic and result['status'] >= 400:
                    response.status_code = 400
                results.append(result)

            if not response.status_code:
                response.status_code = 200

            # if the status is non-working - roll back the transaction
            if response.status_code >= 400:
                raise BulkRollbackError

    except BulkRollbackError:
        pass

    return results
