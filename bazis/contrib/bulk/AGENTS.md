# bazis-bulk — guide for AI agents

Bulk requests for Bazis: `POST <prefix>/bulk/` runs a list of API requests through the
application one after another and returns their responses, optionally in one database
transaction. Use it to create or change several related objects in one call.

## Setup

- Register the route in the root router: `router.register('bazis.contrib.bulk.router')`
  (with `BazisRouter(prefix='/api/v1')` the endpoint is `POST /api/v1/bulk/`).
- The package has no models and no app config: it does not go into `BS_INSTALLED_APPS`.
  If `BS_BAZIS_APPS` is set, list `bazis.contrib.bulk` there, or its setting is not loaded.
- `BS_BAZIS_BULK_MAX_ITEMS`: the maximum number of requests in a bulk request
  (default 1000).

## Request

```json
[
  {"endpoint": "/api/v1/entity/parent_entity/", "method": "POST",
   "body": {"data": {"type": "entity.parent_entity", "bs:action": "add",
                     "attributes": {"name": "Parent 1"}}}},
  {"endpoint": "/api/v1/entity/parent_entity/"}
]
```

- `endpoint`: the full path with the router prefix, and the query string if any.
- `method`: `GET` (default), `POST`, `PUT`, `PATCH`, `DELETE`, `HEAD`, `OPTIONS`
  (case-insensitive). `body`: a JSON object or list, sent as `application/vnd.api+json`
  unless the item sets `Content-Type`.
- `headers`: `[[name, value], ...]` added to (or replacing) the headers of the bulk request.
  Every sub-request gets the headers of the bulk request (`Authorization` included) except
  `Content-Length`, `Content-Type`, `Transfer-Encoding`, `Expect`. Connection headers
  (`Host`, `Connection`, ...), `Forwarded`, `X-Forwarded-For/-Host/-Proto/-Port/-Prefix` and
  `X-Real-IP` cannot be set,
  values must be latin-1 without line breaks; otherwise the bulk request is 422.
- Response: a list of `{"endpoint", "status", "headers", "response"}` in request order;
  `response` is the parsed JSON, or text for a non-JSON body.

## Transactions (`is_atomic`)

- `?is_atomic=true` (default): all sub-requests run in one transaction of the `default`
  database. If any sub-request has a status >= 400 the transaction is rolled back and the
  bulk response is 400; the remaining sub-requests still run and every item keeps its
  own status, so the ids returned by successful items do not exist after the rollback.
- `?is_atomic=false`: every sub-request runs in its own transaction; the bulk response is
  200 whatever the statuses of the items.
- In atomic mode the synchronous code of the sub-requests (FastAPI endpoints and
  dependencies, which run through `anyio.to_thread.run_sync`) runs in one dedicated thread
  that holds the transaction. Database code that does not go through `run_sync` (e.g.
  `sync_to_async` in an `async def` endpoint) does not join the transaction.
- A sub-request that raises an unhandled exception gets the status 500 and does not stop
  the following ones (in atomic mode it causes the rollback).

## Rules

- The bulk endpoint checks nothing itself: each sub-request goes through its route with the
  headers of the bulk request, so authentication and permissions apply per item.
- More than `BAZIS_BULK_MAX_ITEMS` items fails with 400 and the error code `ERR_BULK`;
  nothing runs. An item that is itself a bulk request gets 400 `ERR_BULK` (in atomic mode
  the bulk request is then rolled back).
- Responses are collected in memory: do not use bulk requests for large downloads.
- Code that must behave differently inside a bulk request can call
  `bazis.contrib.bulk.utils.in_bulk_request()`.
