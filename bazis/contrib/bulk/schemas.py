from typing import Any

from pydantic import BaseModel


class BulkRequestItemSchema(BaseModel):
    endpoint: str
    method: str = 'GET'
    body: dict | None = None
    headers: list[tuple[str, Any]] | None = None


class BulkResponseItemSchema(BaseModel):
    endpoint: str
    status: int
    response: str | dict | None
    headers: list[tuple[str, Any]]
