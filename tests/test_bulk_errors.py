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
def test_bulk_nested_rejected(sample_app):
    request_data = [{'endpoint': '/api/v1/bulk/', 'method': 'POST', 'body': []}]

    response = get_api_client(sample_app).post('/api/v1/bulk/', json_data=request_data)

    assert response.status_code == 400
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
def test_bulk_requests_after_bulk_use_the_pool(sample_app):
    """
    The dedicated thread of an atomic bulk request is used only inside the request.
    """
    client = get_api_client(sample_app)
    response = client.post('/api/v1/bulk/', json_data=[_create_parent('in bulk')])
    assert response.status_code == 200

    response = client.post('/api/v1/entity/parent_entity/', json_data=_create_parent('alone')['body'])
    assert response.status_code == 201
    assert set(ParentEntity.objects.values_list('name', flat=True)) == {'in bulk', 'alone'}
