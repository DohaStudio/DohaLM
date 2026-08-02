"""Regular and Server-Sent Events chat endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from server.api.dependencies import (
    get_inference_service,
    get_logger,
    get_request_id,
    get_settings,
)
from server.core.config import APISettings
from server.core.errors import APIError
from server.schemas.chat import AssistantMessage, ChatRequest, ChatResponse, Usage
from server.schemas.common import ErrorResponse
from server.services.inference import InferenceService
from src.inference import (
    GenerationParameters,
    GenerationRequest,
    InferenceMessage,
    ProviderUnavailableError,
)

router = APIRouter(tags=["chat"])


def _inference_request(value: ChatRequest) -> GenerationRequest:
    return GenerationRequest(
        messages=tuple(
            InferenceMessage(role=message.role.value, content=message.content)
            for message in value.messages
        ),
        generation=GenerationParameters(**value.generation.model_dump()),
    )


def _chat_id() -> str:
    return f"chatcmpl_{uuid.uuid4().hex}"


def _event(name: str, data: dict[str, object]) -> str:
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {name}\ndata: {serialized}\n\n"


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def chat(
    body: ChatRequest,
    service: InferenceService = Depends(get_inference_service),
    logger: logging.Logger = Depends(get_logger),
    request_id_value: str = Depends(get_request_id),
) -> ChatResponse:
    result = await service.generate(_inference_request(body))
    logger.info(
        "inference_complete request_id=%s provider=%s model_id=%s finish_reason=%s",
        request_id_value,
        service.provider.provider_name,
        service.provider.model_id,
        result.finish_reason,
    )
    prompt = result.prompt_tokens
    completion = result.completion_tokens
    total = prompt + completion if prompt is not None and completion is not None else None
    return ChatResponse(
        id=_chat_id(),
        model=service.provider.model_id,
        provider=service.provider.provider_name,
        message=AssistantMessage(content=result.content),
        finish_reason=result.finish_reason,
        usage=Usage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        ),
        created_at=datetime.now(timezone.utc),
    )


@router.post(
    "/chat/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "SSE events: start, delta, then exactly one done or error.",
        }
    },
)
async def stream_chat(
    body: ChatRequest,
    service: InferenceService = Depends(get_inference_service),
    settings: APISettings = Depends(get_settings),
    request_id_value: str = Depends(get_request_id),
    logger: logging.Logger = Depends(get_logger),
) -> StreamingResponse:
    generation_request = _inference_request(body)
    completion_id = _chat_id()

    async def events() -> AsyncIterator[str]:
        yield _event(
            "start",
            {
                "id": completion_id,
                "model": service.provider.model_id,
                "provider": service.provider.provider_name,
            },
        )
        try:
            async with asyncio.timeout(settings.request_timeout_seconds):
                async for chunk in service.stream(generation_request):
                    yield _event("delta", {"content": chunk.content})
            yield _event("done", {"finish_reason": "stop"})
            logger.info(
                "stream_complete request_id=%s provider=%s model_id=%s finish_reason=stop",
                request_id_value,
                service.provider.provider_name,
                service.provider.model_id,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            logger.warning("stream_failed request_id=%s error_code=INFERENCE_TIMEOUT", request_id_value)
            yield _event(
                "error",
                {
                    "code": "INFERENCE_TIMEOUT",
                    "message": "Inference request timed out.",
                    "request_id": request_id_value,
                },
            )
        except ProviderUnavailableError as exc:
            logger.warning("stream_failed request_id=%s error_code=%s", request_id_value, exc.code)
            yield _event(
                "error",
                {
                    "code": exc.code,
                    "message": exc.safe_message,
                    "request_id": request_id_value,
                },
            )
        except APIError as exc:
            logger.warning("stream_failed request_id=%s error_code=%s", request_id_value, exc.code)
            yield _event(
                "error",
                {
                    "code": exc.code,
                    "message": exc.safe_message,
                    "request_id": request_id_value,
                },
            )
        except Exception:
            logger.warning("stream_failed request_id=%s error_code=STREAM_FAILED", request_id_value)
            yield _event(
                "error",
                {
                    "code": "STREAM_FAILED",
                    "message": "Streaming inference failed.",
                    "request_id": request_id_value,
                },
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
