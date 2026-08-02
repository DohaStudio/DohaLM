"""Common response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(StrictModel):
    code: str
    message: str
    request_id: str
    details: list[dict[str, object]] = Field(default_factory=list)


class ErrorResponse(StrictModel):
    error: ErrorBody
