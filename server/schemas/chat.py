"""Validated chat and generation schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field, model_validator

from server.schemas.common import StrictModel


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(StrictModel):
    role: MessageRole
    content: str = Field(min_length=1, max_length=8000)

    @model_validator(mode="after")
    def reject_whitespace_only(self) -> "ChatMessage":
        if not self.content.strip():
            raise ValueError("content must not be blank")
        return self


class GenerationOptions(StrictModel):
    max_new_tokens: int = Field(default=256, ge=1, le=1024)
    temperature: float = Field(default=0.7, ge=0, le=2)
    top_p: float = Field(default=0.9, gt=0, le=1)
    repetition_penalty: float = Field(default=1.05, ge=0.5, le=2)
    seed: int | None = None


class ChatRequest(StrictModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=50)
    generation: GenerationOptions = Field(default_factory=GenerationOptions)

    @model_validator(mode="after")
    def validate_conversation(self) -> "ChatRequest":
        if self.messages[-1].role is not MessageRole.USER:
            raise ValueError("last message role must be user")
        if sum(len(message.content) for message in self.messages) > 32_000:
            raise ValueError("total message content exceeds 32000 characters")
        return self


class AssistantMessage(StrictModel):
    role: str = "assistant"
    content: str


class Usage(StrictModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ChatResponse(StrictModel):
    id: str
    model: str
    provider: str
    message: AssistantMessage
    finish_reason: str
    usage: Usage
    created_at: datetime
