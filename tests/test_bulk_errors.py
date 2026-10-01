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

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import ParentEntity


def _create_parent(name: str) -> dict:
    return {
        'endpoint': '/api/v1/entity/parent_entity/',
        'method': 'post',
        'body': {
            'data': {
                'type': 'entity.parent_entity',
                'bs:action': 'add',
                'attributes': {'name': name},
            }
        },
    }


@pytest.mark.django_db(transaction=True)
def test_bulk_failing_sub_request_rolls_back(sample_app):
    request_data = [
        _create_parent('created before the failure'),
        {'endpoint': '/api/v1/failing/', 'method': 'GET'},
        _create_parent('created after the failure'),
    ]

    response = get_api_client(sample_app).post('/api/v1/bulk/', json_data=request_data)

    assert response.status_code == 400
    statuses = [item['status'] for item in response.json()]
    assert statuses == [201, 500, 201]
    assert not ParentEntity.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_bulk_not_atomic(sample_app):
    request_data = [
        _create_parent('created'),
        {'endpoint': '/api/v1/entity/missing/', 'method': 'GET'},
        {'endpoint': '/api/v1/failing/', 'method': 'GET'},
    ]

    response = get_api_client(sample_app).post(
        '/api/v1/bulk/?is_atomic=false', json_data=request_data
    )

    assert response.status_code == 200
    statuses = [item['status'] for item in response.json()]
    assert statuses == [201, 404, 500]
    assert response.json()[1]['response']['errors'][0]['status'] == 404
    assert ParentEntity.objects.filter(name='created').exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('is_atomic', ['true', 'false'])
def test_bulk_nested_rejected(sample_app, is_atomic):
    request_data = [
        {'endpoint': f'/api/v1/bulk/?is_atomic={is_atomic}', 'method': 'POST', 'body': []}
    ]

    response = get_api_client(sample_app).post(
        f'/api/v1/bulk/?is_atomic={is_atomic}', json_data=request_data
    )

    assert response.json()[0]['status'] == 400
    assert response.json()[0]['response']['errors'][0]['code'] == 'ERR_BULK'


@pytest.mark.django_db(transaction=True)
def test_bulk_items_limit(sample_app, settings):
    settings.BAZIS_BULK_MAX_ITEMS = 2
    request_data = [{'endpoint': '/api/v1/entity/parent_entity/'}] * 3

    response = get_api_client(sample_app).post('/api/v1/bulk/', json_data=request_data)

    assert response.status_code == 400
    assert response.json()['errors'][0]['code'] == 'ERR_BULK'


@pytest.mark.django_db(transaction=True)
def test_bulk_dedicated_thread(sample_app):
    """
    The sub-requests of an atomic bulk request run in its dedicated thread, also through
    a nested event loop (no deadlock); other requests use the shared pool.
    """
    client = get_api_client(sample_app)
    request_data = [
        {'endpoint': '/api/v1/echo/', 'headers': [['X-Bulk-Test', 'value']]},
        {'endpoint': '/api/v1/echo/'},
    ]

    response = client.post('/api/v1/bulk/', json_data=request_data)
    assert response.status_code == 200
    first, second = (item['response'] for item in response.json())
    assert first['thread'].startswith('bazis-bulk')
    assert first['nested_thread'] == first['thread']
    assert second['thread'] == first['thread']
    assert first['header'] == 'value'
    assert second['header'] is None

    response = client.post('/api/v1/bulk/?is_atomic=false', json_data=request_data)
    assert response.status_code == 200
    assert not response.json()[0]['response']['thread'].startswith('bazis-bulk')

    response = client.get('/api/v1/echo/')
    assert not response.json()['thread'].startswith('bazis-bulk')
    assert not response.json()['nested_thread'].startswith('bazis-bulk')


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    'headers',
    [
        [['X-Forwarded-For', '10.0.0.1']],
        [['Host', 'example.com']],
        [['bad name', 'value']],
        [['X-Test', 'line\r\nbreak']],
        [['X-Test', 'не latin-1']],
    ],
)
def test_bulk_invalid_headers(sample_app, headers):
    request_data = [{'endpoint': '/api/v1/echo/', 'headers': headers}]

    response = get_api_client(sample_app).post('/api/v1/bulk/', json_data=request_data)

    assert response.status_code == 422


def test_sub_request_failing_after_the_response_started():
    """
    A sub-request that fails after its response started (e.g. a streaming body) was
    reported with the status already sent, so an atomic bulk request committed.
    """
    import asyncio

    from bazis.contrib.bulk.routes import _run_sub_request

    async def app(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'{"data": [', 'more_body': True})
        raise RuntimeError('the stream failed')

    result = {}
    asyncio.run(_run_sub_request(app, {'method': 'GET', 'path': '/x/'}, b'', result))
    assert result['status'] == 500
    assert result['response'] is None


def test_sub_request_failing_after_the_response_completed():
    """
    An error after a complete response (e.g. in a background task) keeps the response.
    """
    import asyncio

    from bazis.contrib.bulk.routes import _run_sub_request

    async def app(scope, receive, send):
        headers = [(b'content-type', b'application/json')]
        await send({'type': 'http.response.start', 'status': 200, 'headers': headers})
        await send({'type': 'http.response.body', 'body': b'{"ok": true}'})
        raise RuntimeError('the background task failed')

    result = {}
    asyncio.run(_run_sub_request(app, {'method': 'GET', 'path': '/x/'}, b'', result))
    assert result['status'] == 200
    assert result['response'] == {'ok': True}
