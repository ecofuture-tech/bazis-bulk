# Bazis Bulk

[![PyPI version](https://img.shields.io/pypi/v/bazis-bulk.svg)](https://pypi.org/project/bazis-bulk/)
[![Python Versions](https://img.shields.io/pypi/pyversions/bazis-bulk.svg)](https://pypi.org/project/bazis-bulk/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

An extension package for Bazis, providing batch request processing with transaction support and asynchronous execution.

## Quick Start

```bash
# Install package
uv add bazis-bulk

# Register route
# router.py
from bazis.core.routing import BazisRouter

router = BazisRouter(prefix='/api/v1')
router.register('bazis.contrib.bulk.router')

# Usage example
curl -X POST http://localhost/api/v1/bulk/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "endpoint": "/api/v1/entity/parent_entity/",
      "method": "POST",
      "body": {
        "data": {
          "type": "entity.parent_entity",
          "bs:action": "add",
          "attributes": {"name": "Parent 1"}
        }
      }
    },
    {
      "endpoint": "/api/v1/entity/child_entity/",
      "method": "POST",
      "body": {
        "data": {
          "type": "entity.child_entity",
          "bs:action": "add",
          "attributes": {"child_name": "Child 1"}
        }
      }
    }
  ]'
```

## Table of Contents

- [Description](#description)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
  - [Route Registration](#route-registration)
  - [Request Format](#request-format)
  - [Request Parameters](#request-parameters)
  - [Response Format](#response-format)
  - [Transactional Mode](#transactional-mode)
  - [Non-transactional Mode](#non-transactional-mode)
- [Examples](#examples)
- [License](#license)
- [Links](#links)

## Description

**Bazis Bulk** is an extension package for the Bazis framework that allows executing multiple API requests in a single HTTP request. The package includes:

- **Batch request execution** — send multiple operations in one request
- **Transactional mode** — all operations execute within a single transaction (atomicity)
- **Non-transactional mode** — operations execute independently
- **Support for all HTTP methods** — GET, POST, PATCH, PUT, DELETE
- **JSON:API support** — work with `included` resources and relationships
- **Dedicated thread for transactions** — guaranteed transaction isolation

**Typical use cases**:
- Creating related entities in one request
- Bulk record updates
- Atomic operations on multiple resources
- Reducing HTTP request count (lower latency)

**This package requires the base `bazis` package to be installed.**

## Requirements

- **Python**: 3.12+
- **bazis**: latest version
- **PostgreSQL**: 12+

## Installation

### Using uv (recommended)

```bash
uv add bazis-bulk
```

### Using pip

```bash
pip install bazis-bulk
```

## Usage

### Route Registration

Add the route to your main `router.py`:

```python
from bazis.core.routing import BazisRouter

router = BazisRouter(prefix='/api/v1')

# Register bulk route
router.register('bazis.contrib.bulk.router')
```

This creates the endpoint: `POST /api/v1/bulk/`

### Request Format

A bulk request is an array of objects, where each object describes a separate HTTP request.

**Single element structure**:

```typescript
{
  "endpoint": string,    // Endpoint path (required)
  "method": string,      // HTTP method: GET, POST, PATCH, PUT, DELETE (required)
  "body": object,        // Request body in JSON:API format (optional)
  "headers": array       // Additional headers (optional, currently ignored)
}
```

**Example**:

```json
[
  {
    "endpoint": "/api/v1/entity/parent_entity/",
    "method": "POST",
    "body": {
      "data": {
        "type": "entity.parent_entity",
        "bs:action": "add",
        "attributes": {
          "name": "New Parent"
        }
      }
    }
  }
]
```

### Request Parameters

#### is_atomic (query parameter)

Defines the request execution mode:

- `is_atomic=true` (default) — **transactional mode**
  - All operations execute within a single transaction
  - Any operation error rolls back the entire transaction
  - Response status: 400 if errors occur

- `is_atomic=false` — **non-transactional mode**
  - Operations execute independently
  - Error in one operation doesn't affect others
  - Response status: 200 even with errors in individual operations

**Examples**:

```bash
# Transactional mode (default)
POST /api/v1/bulk/
POST /api/v1/bulk/?is_atomic=true

# Non-transactional mode
POST /api/v1/bulk/?is_atomic=false
```

### Response Format

Each response item contains the original endpoint, HTTP status, headers, and the parsed body.

**Single element structure**:

```typescript
{
  "endpoint": string,    // Endpoint path (required)
  "status": number,      // HTTP status code (required)
  "headers": array,      // ASGI response headers as [name, value] pairs
  "response": object     // Parsed JSON for JSON responses, raw body otherwise (may be null)
}
```

Headers are returned as emitted by the ASGI app (typically byte pairs).

### Transactional Mode

In transactional mode, all operations execute in a dedicated thread with a single database transaction.

**Features**:

- All operations either succeed completely or rollback entirely
- Any operation error causes transaction rollback
- Overall response status: 400 if errors occur

**Request example**:

```bash
POST /api/v1/bulk/?is_atomic=true
Content-Type: application/json
Authorization: Bearer YOUR_TOKEN

[
  {
    "endpoint": "/api/v1/orders/order/",
    "method": "POST",
    "body": {
      "data": {
        "type": "myapp.order",
        "bs:action": "add",
        "attributes": {
          "description": "Order 1",
          "amount": 1000
        }
      }
    }
  },
  {
    "endpoint": "/api/v1/orders/order/",
    "method": "POST",
    "body": {
      "data": {
        "type": "myapp.order",
        "bs:action": "add",
        "attributes": {
          "description": "Order 2",
          "amount": 2000
        }
      }
    }
  }
]
```

**Success response** (status 200):

```json
[
  {
    "endpoint": "/api/v1/orders/order/",
    "status": 201,
    "headers": [
      ["content-type", "application/vnd.api+json"]
    ],
    "response": {
      "data": {
        "type": "myapp.order",
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "attributes": {
          "description": "Order 1",
          "amount": 1000
        }
      }
    }
  },
  {
    "endpoint": "/api/v1/orders/order/",
    "status": 201,
    "response": {
      "data": {
        "type": "myapp.order",
        "id": "987e6543-e21b-32d1-b654-426614174001",
        "attributes": {
          "description": "Order 2",
          "amount": 2000
        }
      }
    }
  }
]
```

**Error response** (status 400, all operations rolled back):

```json
[
  {
    "endpoint": "/api/v1/orders/order/",
    "status": 201,
    "response": {
      "data": {
        "type": "myapp.order",
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "attributes": {
          "description": "Order 1"
        }
      }
    }
  },
  {
    "endpoint": "/api/v1/orders/order/",
    "status": 403,
    "response": {
      "errors": [
        {
          "status": 403,
          "detail": "Permission denied"
        }
      ]
    }
  }
]
```

### Non-transactional Mode

In non-transactional mode, each operation executes independently in a thread pool.

**Features**:

- Operations execute independently
- Error in one operation doesn't affect others
- Overall response status: always 200

**Request example**:

```bash
POST /api/v1/bulk/?is_atomic=false
Content-Type: application/json
Authorization: Bearer YOUR_TOKEN

[
  {
    "endpoint": "/api/v1/orders/order/",
    "method": "POST",
    "body": {
      "data": {
        "type": "myapp.order",
        "bs:action": "add",
        "attributes": {"description": "Order 1"}
      }
    }
  },
  {
    "endpoint": "/api/v1/orders/order/999/",
    "method": "DELETE",
    "body": {}
  }
]
```

**Response** (status 200, even with errors):

```json
[
  {
    "endpoint": "/api/v1/orders/order/",
    "status": 201,
    "response": {
      "data": {
        "type": "myapp.order",
        "id": "123e4567-e89b-12d3-a456-426614174000"
      }
    }
  },
  {
    "endpoint": "/api/v1/orders/order/999/",
    "status": 404,
    "response": {
      "errors": [
        {
          "status": 404,
          "detail": "Not found"
        }
      ]
    }
  }
]
```

## Examples

### Example 1: Creating Related Entities

Creating a parent entity and two child entities in one transaction:

```json
[
  {
    "endpoint": "/api/v1/entity/parent_entity/",
    "method": "POST",
    "body": {
      "data": {
        "type": "entity.parent_entity",
        "bs:action": "add",
        "attributes": {
          "name": "Parent Entity"
        }
      }
    }
  },
  {
    "endpoint": "/api/v1/entity/child_entity/",
    "method": "POST",
    "body": {
      "data": {
        "type": "entity.child_entity",
        "bs:action": "add",
        "attributes": {
          "child_name": "Child 1"
        }
      }
    }
  },
  {
    "endpoint": "/api/v1/entity/child_entity/",
    "method": "POST",
    "body": {
      "data": {
        "type": "entity.child_entity",
        "bs:action": "add",
        "attributes": {
          "child_name": "Child 2"
        }
      }
    }
  }
]
```

### Example 2: Update with Included Resources

Updating a parent entity and its related children:

```json
[
  {
    "endpoint": "/api/v1/entity/parent_entity/123/?include=extended_entity,dependent_entities",
    "method": "PATCH",
    "body": {
      "data": {
        "id": "123",
        "type": "entity.parent_entity",
        "bs:action": "change",
        "attributes": {
          "name": "Updated Parent"
        }
      },
      "included": [
        {
          "id": "456",
          "type": "entity.extended_entity",
          "bs:action": "change",
          "attributes": {
            "extended_name": "Updated Extended"
          }
        },
        {
          "type": "entity.dependent_entity",
          "bs:action": "add",
          "attributes": {
            "dependent_name": "New Dependent"
          },
          "relationships": {
            "parent_entity": {
              "data": {
                "id": "123",
                "type": "entity.parent_entity"
              }
            }
          }
        }
      ]
    }
  }
]
```

### Example 3: Bulk Update

Updating multiple records simultaneously:

```json
[
  {
    "endpoint": "/api/v1/entity/child_entity/child-1/",
    "method": "PATCH",
    "body": {
      "data": {
        "id": "child-1",
        "type": "entity.child_entity",
        "bs:action": "change",
        "attributes": {
          "child_name": "Updated Child 1"
        }
      }
    }
  },
  {
    "endpoint": "/api/v1/entity/child_entity/child-2/",
    "method": "PATCH",
    "body": {
      "data": {
        "id": "child-2",
        "type": "entity.child_entity",
        "bs:action": "change",
        "attributes": {
          "child_name": "Updated Child 2"
        }
      }
    }
  },
  {
    "endpoint": "/api/v1/entity/child_entity/child-3/",
    "method": "PATCH",
    "body": {
      "data": {
        "id": "child-3",
        "type": "entity.child_entity",
        "bs:action": "change",
        "attributes": {
          "child_name": "Updated Child 3"
        }
      }
    }
  }
]
```

### Example 4: Mixed Operations

Create, update, and delete in one request:

```json
[
  {
    "endpoint": "/api/v1/entity/parent_entity/",
    "method": "POST",
    "body": {
      "data": {
        "type": "entity.parent_entity",
        "bs:action": "add",
        "attributes": {"name": "New Parent"}
      }
    }
  },
  {
    "endpoint": "/api/v1/entity/parent_entity/existing-id/",
    "method": "PATCH",
    "body": {
      "data": {
        "id": "existing-id",
        "type": "entity.parent_entity",
        "bs:action": "change",
        "attributes": {"price": "845.42"}
      }
    }
  },
  {
    "endpoint": "/api/v1/entity/child_entity/old-id/",
    "method": "DELETE",
    "body": {}
  }
]
```

### Example 5: JavaScript Client

```javascript
class BulkClient {
  constructor(apiUrl, token) {
    this.apiUrl = apiUrl;
    this.token = token;
  }

  async executeBulk(operations, isAtomic = true) {
    const url = `${this.apiUrl}/bulk/?is_atomic=${isAtomic}`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(operations)
    });

    if (!response.ok) {
      throw new Error(`Bulk request failed: ${response.status}`);
    }

    return await response.json();
  }

  async createMultiple(entities, isAtomic = true) {
    const operations = entities.map(entity => ({
      endpoint: entity.endpoint,
      method: 'POST',
      body: {
        data: {
          type: entity.type,
          'bs:action': 'add',
          attributes: entity.attributes,
          relationships: entity.relationships
        }
      }
    }));

    return await this.executeBulk(operations, isAtomic);
  }

  async updateMultiple(updates, isAtomic = true) {
    const operations = updates.map(update => ({
      endpoint: `${update.endpoint}/${update.id}/`,
      method: 'PATCH',
      body: {
        data: {
          id: update.id,
          type: update.type,
          'bs:action': 'change',
          attributes: update.attributes
        }
      }
    }));

    return await this.executeBulk(operations, isAtomic);
  }
}

// Usage
const bulk = new BulkClient('http://api.example.com/api/v1', jwtToken);

// Create multiple entities atomically
const results = await bulk.createMultiple([
  {
    endpoint: '/api/v1/orders/order',
    type: 'myapp.order',
    attributes: { description: 'Order 1', amount: 1000 }
  },
  {
    endpoint: '/api/v1/orders/order',
    type: 'myapp.order',
    attributes: { description: 'Order 2', amount: 2000 }
  }
], true);

console.log('Created:', results);

// Bulk update without transaction
await bulk.updateMultiple([
  {
    endpoint: '/api/v1/orders/order',
    id: 'order-1',
    type: 'myapp.order',
    attributes: { status: 'completed' }
  },
  {
    endpoint: '/api/v1/orders/order',
    id: 'order-2',
    type: 'myapp.order',
    attributes: { status: 'completed' }
  }
], false);
```

### Example 6: Python Client

```python
import requests
from typing import List, Dict, Any

class BulkClient:
    def __init__(self, api_url: str, token: str):
        self.api_url = api_url
        self.token = token
        self.headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

    def execute_bulk(
        self,
        operations: List[Dict[str, Any]],
        is_atomic: bool = True
    ) -> List[Dict[str, Any]]:
        """Execute bulk request"""
        url = f"{self.api_url}/bulk/?is_atomic={str(is_atomic).lower()}"

        response = requests.post(
            url,
            headers=self.headers,
            json=operations
        )
        response.raise_for_status()

        return response.json()

    def create_with_related(
        self,
        parent_data: Dict[str, Any],
        children_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Create parent entity with children in one transaction"""
        operations = [
            {
                'endpoint': parent_data['endpoint'],
                'method': 'POST',
                'body': {
                    'data': {
                        'type': parent_data['type'],
                        'bs:action': 'add',
                        'attributes': parent_data['attributes']
                    }
                }
            }
        ]

        for child in children_data:
            operations.append({
                'endpoint': child['endpoint'],
                'method': 'POST',
                'body': {
                    'data': {
                        'type': child['type'],
                        'bs:action': 'add',
                        'attributes': child['attributes'],
                        'relationships': child.get('relationships', {})
                    }
                }
            })

        return self.execute_bulk(operations, is_atomic=True)

# Usage
bulk = BulkClient('http://api.example.com/api/v1', jwt_token)

# Create order with items
results = bulk.create_with_related(
    parent_data={
        'endpoint': '/api/v1/orders/order',
        'type': 'myapp.order',
        'attributes': {
            'description': 'New Order',
            'customer': 'John Doe'
        }
    },
    children_data=[
        {
            'endpoint': '/api/v1/orders/orderitem',
            'type': 'myapp.orderitem',
            'attributes': {
                'product': 'Product 1',
                'quantity': 2,
                'price': '100.00'
            }
        },
        {
            'endpoint': '/api/v1/orders/orderitem',
            'type': 'myapp.orderitem',
            'attributes': {
                'product': 'Product 2',
                'quantity': 1,
                'price': '50.00'
            }
        }
    ]
)

print(f"Created order with {len(results) - 1} items")
```

## License

Apache License 2.0

See [LICENSE](LICENSE) file for details.

## Links

- [Bazis Documentation](https://github.com/ecofuture-tech/bazis) — main repository
- [Bazis Bulk Repository](https://github.com/ecofuture-tech/bazis-bulk) — package repository
- [Issue Tracker](https://github.com/ecofuture-tech/bazis-bulk/issues) — report bugs or request features

## Support

If you have questions or issues:
- Review the [Bazis documentation](https://github.com/ecofuture-tech/bazis)
- Search through [existing issues](https://github.com/ecofuture-tech/bazis-bulk/issues)
- Create a [new issue](https://github.com/ecofuture-tech/bazis-bulk/issues/new) with detailed information

---

Made with ❤️ by the Bazis team
