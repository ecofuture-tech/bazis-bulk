from urllib.parse import urlencode

import pytest
from bazis_test_utils.utils import get_api_client

from tests import factories


@pytest.mark.django_db(transaction=True)
def test_bulk_view(sample_app):
    factories.ParentEntityFactory.create_batch(15, child_entities=True)

    parent_entity_query = urlencode(
        {
            'sort': 'id',
            'page[limit]': 5,
            'meta': 'pagination',
        }
    )

    child_entity_query = urlencode(
        {
            'sort': 'id',
            'filter': 'child_is_active=true',
        }
    )

    request_data = [
        {
            'endpoint': f'/api/v1/entity/parent_entity/?{parent_entity_query}',
            'method': 'GET',
        },
        {
            'endpoint': f'/api/v1/entity/child_entity/?{child_entity_query}',
            'method': 'GET',
        },
    ]

    bulk_response = get_api_client(sample_app).post('/api/v1/bulk/', json_data=request_data)

    assert bulk_response.status_code == 200

    bulk_data = bulk_response.json()

    # parent entity test case

    parent_entity_response = bulk_data[0]

    assert parent_entity_response['status'] == 200
    assert parent_entity_response['endpoint'] == request_data[0]['endpoint']

    data = parent_entity_response['response']

    assert len(data['data']) == 5

    for it in data['data']:
        assert it['type'] == 'entity.parent_entity'
        assert it['bs:action'] == 'view'
        assert 'id' in it
        assert 'attributes' in it
        assert 'relationships' in it

        _attributes = it['attributes']
        _relationships = it['relationships']

        assert 'dt_created' in _attributes
        assert 'dt_updated' in _attributes
        assert 'name' in _attributes
        assert 'description' in _attributes
        assert 'is_active' in _attributes
        assert 'price' in _attributes
        assert 'dt_approved' in _attributes

        assert 'child_entities' in _relationships
        assert 'extended_entity' in _relationships
        assert 'dependent_entities' in _relationships

        _extended_entity = _relationships['extended_entity']
        _dependent_entities = _relationships['dependent_entities']

        assert _extended_entity['data']['id'] is not None
        assert _extended_entity['data']['type'] == 'entity.extended_entity'
        assert isinstance(_dependent_entities['data'], list)
        assert _dependent_entities['data'][0]['id'] is not None
        assert _dependent_entities['data'][0]['type'] == 'entity.dependent_entity'

    # child entity test case

    child_entity_response = bulk_data[1]

    assert child_entity_response['status'] == 200
    assert child_entity_response['endpoint'] == request_data[1]['endpoint']

    data = child_entity_response['response']

    for it in data['data']:
        assert it['attributes']['child_is_active'] is True


@pytest.mark.django_db(transaction=True)
def test_bulk_update(sample_app):
    parent_entity = factories.ParentEntityFactory.create(
        name='Parent test name',
        child_entities=False,
        dependent_entities=None,
        extended_entity=None,
    )
    extended_entity = factories.ExtendedEntityFactory.create(
        extended_name='Extended test name', parent_entity=parent_entity
    )
    dependent_entity = factories.DependentEntityFactory.create(
        dependent_name='Dependent test name', parent_entity=parent_entity
    )
    child_entity_1 = factories.ChildEntityFactory.create(
        child_name='Child test name',
    )
    child_entity_2 = factories.ChildEntityFactory.create(
        child_name='Child test name 2',
    )
    child_entity_3 = factories.ChildEntityFactory.create(
        child_name='Child test name 3',
    )
    parent_entity.child_entities.add(child_entity_1)
    parent_entity.child_entities.add(child_entity_2)
    parent_entity.child_entities.add(child_entity_3)

    #

    parent_entity_query = urlencode(
        {
            'include': 'extended_entity,dependent_entities',
        }
    )

    request_data = [
        {
            'endpoint': f'/api/v1/entity/parent_entity/{parent_entity.pk}/?{parent_entity_query}',
            'method': 'PATCH',
            'body': {
                'data': {
                    'id': str(parent_entity.pk),
                    'type': 'entity.parent_entity',
                    'bs:action': 'change',
                    'attributes': {
                        'name': 'New parent test name',
                    },
                },
                'included': [
                    {
                        'id': str(extended_entity.pk),
                        'type': 'entity.extended_entity',
                        'bs:action': 'change',
                        'attributes': {
                            'extended_name': 'New extended test name',
                        },
                    },
                    {
                        'type': 'entity.dependent_entity',
                        'bs:action': 'add',
                        'attributes': {
                            'dependent_name': 'Dependent test name 2',
                            'dependent_description': 'Dependent test description 2',
                            'dependent_is_active': True,
                            'dependent_price': '500.41',
                            'dependent_dt_approved': '2024-01-14T17:54:12Z',
                        },
                        'relationships': {
                            'parent_entity': {
                                'data': {
                                    'id': str(parent_entity.pk),
                                    'type': 'entity.parent_entity',
                                },
                            },
                        },
                    },
                    {
                        'id': str(dependent_entity.pk),
                        'type': 'entity.dependent_entity',
                        'bs:action': 'change',
                        'attributes': {
                            'dependent_name': 'New dependent test name',
                        },
                    },
                ],
            },
        },
        {
            'endpoint': f'/api/v1/entity/child_entity/{child_entity_1.pk}/',
            'method': 'PATCH',
            'body': {
                'data': {
                    'id': str(child_entity_1.pk),
                    'type': 'entity.child_entity',
                    'bs:action': 'change',
                    'attributes': {
                        'child_name': 'New child test name',
                    },
                },
            },
        },
        {
            'endpoint': '/api/v1/entity/child_entity/',
            'method': 'POST',
            'body': {
                'data': {
                    'type': 'entity.child_entity',
                    'bs:action': 'add',
                    'attributes': {
                        'child_name': 'Child test name 4',
                        'child_description': 'Child test description 4',
                        'child_is_active': True,
                        'child_price': '421.74',
                        'child_dt_approved': '2024-01-14T17:54:12Z',
                    },
                    'relationships': {
                        'parent_entities': {
                            'data': [
                                {
                                    'id': str(parent_entity.pk),
                                    'type': 'entity.parent_entity',
                                }
                            ],
                        },
                    },
                },
            },
        },
    ]

    bulk_response = get_api_client(sample_app).post('/api/v1/bulk/', json_data=request_data)

    assert bulk_response.status_code == 200

    bulk_data = bulk_response.json()

    # parent entity test case

    parent_entity_response = bulk_data[0]

    assert parent_entity_response['status'] == 200
    assert parent_entity_response['endpoint'] == request_data[0]['endpoint']

    data = parent_entity_response['response']

    it = data['data']
    assert it['type'] == 'entity.parent_entity'
    assert it['bs:action'] == 'view'
    assert it['attributes']['name'] == 'New parent test name'

    relationships = it['relationships']

    assert relationships['extended_entity']['data']['type'] == 'entity.extended_entity'
    assert relationships['dependent_entities']['data'][0]['type'] == 'entity.dependent_entity'
    assert relationships['dependent_entities']['data'][1]['type'] == 'entity.dependent_entity'

    for incl in data['included']:
        if incl['type'] == 'entity.extended_entity' and incl['id'] == str(extended_entity.pk):
            assert incl['attributes']['extended_name'] == 'New extended test name'
        if incl['type'] == 'entity.dependent_entity' and incl['id'] == str(dependent_entity.pk):
            assert incl['attributes']['dependent_name'] == 'New dependent test name'

    # child entity test case

    child_entity_1_response = bulk_data[1]

    assert child_entity_1_response['status'] == 200
    assert child_entity_1_response['endpoint'] == request_data[1]['endpoint']

    data = child_entity_1_response['response']

    it = data['data']
    assert it['type'] == 'entity.child_entity'
    assert it['bs:action'] == 'view'
    assert it['attributes']['child_name'] == 'New child test name'
    assert it['relationships']['parent_entities']['data'][0]['id'] == str(parent_entity.pk)

    child_entity_2_response = bulk_data[2]
    assert child_entity_2_response['status'] == 201
    assert child_entity_2_response['endpoint'] == request_data[2]['endpoint']

    data = child_entity_2_response['response']

    it = data['data']
    assert it['type'] == 'entity.child_entity'
    assert it['bs:action'] == 'view'
    assert it['attributes']['child_name'] == 'Child test name 4'
    assert it['relationships']['parent_entities']['data'][0]['id'] == str(parent_entity.pk)


@pytest.mark.django_db(transaction=True)
def test_bulk_update_rollback(sample_app):
    parent_entity = factories.ParentEntityFactory.create(
        name='Parent test name',
        child_entities=False,
        dependent_entities=None,
        extended_entity=None,
    )
    extended_entity = factories.ExtendedEntityFactory.create(
        extended_name='Extended test name', parent_entity=parent_entity
    )
    dependent_entity = factories.DependentEntityFactory.create(
        dependent_name='Dependent test name', parent_entity=parent_entity
    )
    child_entity_1 = factories.ChildEntityFactory.create(
        child_name='Child test name',
    )
    child_entity_2 = factories.ChildEntityFactory.create(
        child_name='Child test name 2',
    )
    child_entity_3 = factories.ChildEntityFactory.create(
        child_name='Child test name 3',
    )
    parent_entity.child_entities.add(child_entity_1)
    parent_entity.child_entities.add(child_entity_2)
    parent_entity.child_entities.add(child_entity_3)

    #

    parent_entity_query = urlencode(
        {
            'include': 'extended_entity,dependent_entities',
        }
    )

    request_data = [
        {
            'endpoint': f'/api/v1/entity/parent_entity/{parent_entity.pk}/?{parent_entity_query}',
            'method': 'PATCH',
            'body': {
                'data': {
                    'id': str(parent_entity.pk),
                    'type': 'entity.parent_entity',
                    'bs:action': 'change',
                    'attributes': {
                        'name': 'New parent test name',
                    },
                },
                'included': [
                    {
                        'id': str(extended_entity.pk),
                        'type': 'entity.extended_entity',
                        'bs:action': 'change',
                        'attributes': {
                            'extended_name': 'New extended test name',
                        },
                    },
                    {
                        'type': 'entity.dependent_entity',
                        'bs:action': 'add',
                        'attributes': {
                            'dependent_name': 'Dependent test name 2',
                            'dependent_description': 'Dependent test description 2',
                            'dependent_is_active': True,
                            'dependent_price': '500.41',
                            'dependent_dt_approved': '2024-01-14T17:54:12Z',
                        },
                        'relationships': {
                            'parent_entity': {
                                'data': {
                                    'id': str(parent_entity.pk),
                                    'type': 'entity.parent_entity',
                                },
                            },
                        },
                    },
                    {
                        'id': str(dependent_entity.pk),
                        'type': 'entity.dependent_entity',
                        'bs:action': 'change',
                        'attributes': {
                            'dependent_name': 'New dependent test name',
                        },
                    },
                ],
            },
        },
        {
            'endpoint': f'/api/v1/entity/child_entity/{child_entity_1.pk}/',
            'method': 'PATCH',
            'body': {
                'data': {
                    'id': str(child_entity_1.pk),
                    'type': 'entity.child_entity',
                    'bs:action': 'change',
                    'attributes': {
                        'child_name': 'New child test name',
                        'child_price': 'Wrong price',
                    },
                },
            },
        },
        {
            'endpoint': '/api/v1/entity/child_entity/',
            'method': 'POST',
            'body': {
                'data': {
                    'type': 'entity.child_entity',
                    'bs:action': 'add',
                    'attributes': {
                        'child_name': 'Child test name 4',
                        'child_description': 'Child test description 4',
                        'child_is_active': True,
                        'child_price': '421.74',
                        'child_dt_approved': '2024-01-14T17:54:12Z',
                    },
                    'relationships': {
                        'parent_entities': {
                            'data': [
                                {
                                    'id': str(parent_entity.pk),
                                    'type': 'entity.parent_entity',
                                }
                            ],
                        },
                    },
                },
            },
        },
    ]

    #
    # Test for rollback if one of the requests is invalid (is_atomic=true)
    #

    bulk_response = get_api_client(sample_app).post(
        '/api/v1/bulk/?is_atomic=true', json_data=request_data
    )

    assert bulk_response.status_code == 400

    bulk_data = bulk_response.json()

    # parent entity test case

    parent_entity_response = bulk_data[0]

    assert parent_entity_response['status'] == 200
    assert parent_entity_response['endpoint'] == request_data[0]['endpoint']

    data = parent_entity_response['response']

    it = data['data']
    assert it['attributes']['name'] == 'New parent test name'

    # child entity test case

    child_entity_1_response = bulk_data[1]

    assert child_entity_1_response['status'] == 422
    assert child_entity_1_response['endpoint'] == request_data[1]['endpoint']

    data = child_entity_1_response['response']

    err = data['errors'][0]
    assert err['status'] == 422
    assert err['code'] == 'ERR_VALIDATE'
    assert err['title'] == 'decimal_parsing'
    assert err['detail'] == 'Input should be a valid decimal'
    assert err['source']['pointer'] == '/attributes/child_price'

    child_entity_2_response = bulk_data[2]
    assert child_entity_2_response['status'] == 201
    assert child_entity_2_response['endpoint'] == request_data[2]['endpoint']

    data = child_entity_2_response['response']

    it = data['data']
    assert it['attributes']['child_name'] == 'Child test name 4'
    assert it['relationships']['parent_entities']['data'][0]['id'] == str(parent_entity.pk)

    # check that nothing was changed because of the error in the second request

    parent_entity.refresh_from_db()
    assert parent_entity.name == 'Parent test name'

    extended_entity.refresh_from_db()
    assert extended_entity.extended_name == 'Extended test name'

    dependent_entity.refresh_from_db()
    assert dependent_entity.dependent_name == 'Dependent test name'

    child_entity_1.refresh_from_db()
    assert child_entity_1.child_name == 'Child test name'

    assert parent_entity.dependent_entities.count() == 1
    assert parent_entity.child_entities.count() == 3

    #
    # Test that the transaction is not rolled back if is_atomic=false
    #

    bulk_response = get_api_client(sample_app).post(
        '/api/v1/bulk/?is_atomic=false', json_data=request_data
    )

    assert bulk_response.status_code == 200

    bulk_data = bulk_response.json()

    # parent entity test case

    parent_entity_response = bulk_data[0]

    assert parent_entity_response['status'] == 200
    assert parent_entity_response['endpoint'] == request_data[0]['endpoint']

    data = parent_entity_response['response']

    it = data['data']
    assert it['attributes']['name'] == 'New parent test name'

    # child entity test case

    child_entity_1_response = bulk_data[1]

    assert child_entity_1_response['status'] == 422
    assert child_entity_1_response['endpoint'] == request_data[1]['endpoint']

    data = child_entity_1_response['response']

    err = data['errors'][0]
    assert err['status'] == 422
    assert err['code'] == 'ERR_VALIDATE'
    assert err['title'] == 'decimal_parsing'
    assert err['detail'] == 'Input should be a valid decimal'
    assert err['source']['pointer'] == '/attributes/child_price'

    child_entity_2_response = bulk_data[2]
    assert child_entity_2_response['status'] == 201
    assert child_entity_2_response['endpoint'] == request_data[2]['endpoint']

    data = child_entity_2_response['response']

    it = data['data']
    assert it['attributes']['child_name'] == 'Child test name 4'
    assert it['relationships']['parent_entities']['data'][0]['id'] == str(parent_entity.pk)

    # check that the first and third requests were executed and the second was not

    parent_entity.refresh_from_db()
    assert parent_entity.name == 'New parent test name'

    extended_entity.refresh_from_db()
    assert extended_entity.extended_name == 'New extended test name'

    dependent_entity.refresh_from_db()
    assert dependent_entity.dependent_name == 'New dependent test name'

    child_entity_1.refresh_from_db()
    assert child_entity_1.child_name == 'Child test name'

    assert parent_entity.dependent_entities.count() == 2
    assert parent_entity.child_entities.count() == 4
