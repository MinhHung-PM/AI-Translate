from __future__ import annotations

from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, ConfigDict, StringConstraints


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class InModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class PageParams:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1, le=10_000)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


ShortText = Annotated[str, StringConstraints(min_length=1, max_length=300, strip_whitespace=True)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)]
LongText = Annotated[str, StringConstraints(max_length=10_000)]
