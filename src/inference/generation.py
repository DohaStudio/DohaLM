"""Qwen chat-template generation helpers with cooperative cancellation."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from src.inference.base import GenerationRequest, GenerationResult
from src.inference.model_loader import (
    BASE_QWEN_EOS_TOKEN_ID,
    BASE_QWEN_PAD_TOKEN_ID,
    LoadedBaseQwen,
)


def _messages(request: GenerationRequest) -> list[dict[str, str]]:
    return [
        {"role": message.role, "content": message.content.strip()}
        for message in request.messages
    ]


def prepare_inputs(
    loaded: LoadedBaseQwen, request: GenerationRequest
) -> tuple[dict[str, Any], int]:
    prompt = loaded.tokenizer.apply_chat_template(
        _messages(request),
        tokenize=False,
        add_generation_prompt=True,
    )
    encoded = loaded.tokenizer(prompt, return_tensors="pt", add_special_tokens=False)
    inputs = {
        name: value.to("cuda:0", non_blocking=True) for name, value in encoded.items()
    }
    return inputs, int(inputs["input_ids"].shape[-1])


def generation_kwargs(
    request: GenerationRequest, cancel_event: threading.Event
) -> dict[str, Any]:
    from transformers import StoppingCriteria, StoppingCriteriaList

    class CancellationCriteria(StoppingCriteria):
        def __call__(self, input_ids: Any, scores: Any, **kwargs: Any) -> bool:
            del input_ids, scores, kwargs
            return cancel_event.is_set()

    values: dict[str, Any] = {
        "max_new_tokens": request.generation.max_new_tokens,
        "repetition_penalty": request.generation.repetition_penalty,
        "eos_token_id": BASE_QWEN_EOS_TOKEN_ID,
        "pad_token_id": BASE_QWEN_PAD_TOKEN_ID,
        "use_cache": True,
        "stopping_criteria": StoppingCriteriaList([CancellationCriteria()]),
    }
    if request.generation.temperature == 0:
        values["do_sample"] = False
    else:
        values.update(
            do_sample=True,
            temperature=request.generation.temperature,
            top_p=request.generation.top_p,
        )
    return values


def generate_sync(
    loaded: LoadedBaseQwen,
    request: GenerationRequest,
    cancel_event: threading.Event,
) -> GenerationResult:
    inputs, prompt_tokens = prepare_inputs(loaded, request)
    if request.generation.seed is not None:
        loaded.torch.manual_seed(request.generation.seed)
        loaded.torch.cuda.manual_seed_all(request.generation.seed)
    with loaded.torch.inference_mode():
        output = loaded.model.generate(
            **inputs,
            **generation_kwargs(request, cancel_event),
        )
    token_ids = output[0, prompt_tokens:]
    completion_tokens = int(token_ids.shape[-1])
    content = loaded.tokenizer.decode(token_ids, skip_special_tokens=True)
    hit_eos = bool(
        completion_tokens and int(token_ids[-1].item()) == BASE_QWEN_EOS_TOKEN_ID
    )
    finish_reason = "stop" if hit_eos else "length"
    if cancel_event.is_set():
        finish_reason = "cancelled"
    return GenerationResult(
        content=content,
        finish_reason=finish_reason,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


_STREAM_END = object()


@dataclass
class StreamingSession:
    streamer: Any
    worker: threading.Thread
    cancel_event: threading.Event
    error: list[BaseException]
    finish_reason: list[str]

    def next_text(self) -> str | object:
        try:
            return next(self.streamer)
        except StopIteration:
            return _STREAM_END

    def cancel(self) -> None:
        self.cancel_event.set()

    def join(self) -> None:
        self.worker.join()

    @property
    def ended(self) -> bool:
        return not self.worker.is_alive()


def start_stream(
    loaded: LoadedBaseQwen, request: GenerationRequest
) -> StreamingSession:
    from transformers import TextIteratorStreamer

    cancel_event = threading.Event()
    inputs, _ = prepare_inputs(loaded, request)
    streamer = TextIteratorStreamer(
        loaded.tokenizer,
        skip_prompt=True,
        skip_special_tokens=True,
    )
    errors: list[BaseException] = []
    finish_reasons: list[str] = []

    def target() -> None:
        try:
            if request.generation.seed is not None:
                loaded.torch.manual_seed(request.generation.seed)
                loaded.torch.cuda.manual_seed_all(request.generation.seed)
            with loaded.torch.inference_mode():
                output = loaded.model.generate(
                    **inputs,
                    streamer=streamer,
                    **generation_kwargs(request, cancel_event),
                )
            token_ids = output[0, inputs["input_ids"].shape[-1] :]
            hit_eos = bool(
                token_ids.shape[-1]
                and int(token_ids[-1].item()) == BASE_QWEN_EOS_TOKEN_ID
            )
            finish_reasons.append(
                "cancelled"
                if cancel_event.is_set()
                else ("stop" if hit_eos else "length")
            )
        except Exception as exc:
            errors.append(exc)
            streamer.end()

    worker = threading.Thread(target=target, name="base-qwen-stream", daemon=False)
    worker.start()
    return StreamingSession(streamer, worker, cancel_event, errors, finish_reasons)


def stream_end_marker() -> object:
    return _STREAM_END
