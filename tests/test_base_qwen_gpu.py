from __future__ import annotations

import asyncio
import os
import re
import threading
from pathlib import Path

import pytest

from src.inference import GenerationParameters, GenerationRequest, InferenceMessage
from src.inference.generation import prepare_inputs
from src.inference.model_loader import BaseQwenConfig
from src.inference.providers import BaseQwenProvider

pytestmark = pytest.mark.gpu


def _enabled_snapshot() -> Path:
    if os.environ.get("DOHALM_RUN_GPU_TESTS") != "1":
        pytest.skip("set DOHALM_RUN_GPU_TESTS=1 for the explicit local-model test")
    value = os.environ.get("DOHALM_BASE_MODEL_SNAPSHOT")
    if not value:
        pytest.skip("DOHALM_BASE_MODEL_SNAPSHOT is required")
    return Path(value)


def _request(max_new_tokens: int = 16) -> GenerationRequest:
    return GenerationRequest(
        messages=(
            InferenceMessage(role="user", content="한국어로 짧게 인사해 주세요."),
        ),
        generation=GenerationParameters(
            max_new_tokens=max_new_tokens,
            temperature=0,
            seed=17,
        ),
    )


def test_local_base_qwen_generate_stream_cancel_and_unload() -> None:
    async def run() -> None:
        import torch

        provider = BaseQwenProvider(
            BaseQwenConfig(
                snapshot=_enabled_snapshot(),
                quantization=os.environ.get("DOHALM_BASE_MODEL_QUANTIZATION", "bf16"),
                generation_timeout_seconds=90,
            )
        )
        result = await provider.generate(_request())
        assert result.content.strip()
        assert re.search(r"[가-힣]", result.content)
        assert result.prompt_tokens and result.prompt_tokens > 0
        assert result.completion_tokens and result.completion_tokens > 0
        assert result.finish_reason in {"stop", "length"}

        loaded = provider._loaded
        assert loaded is not None
        assert {parameter.device.type for parameter in loaded.model.parameters()} == {
            "cuda"
        }
        assert all(
            str(value) not in {"cpu", "disk"}
            for value in getattr(loaded.model, "hf_device_map", {}).values()
        )
        inputs, _ = prepare_inputs(loaded, _request(1))
        with torch.inference_mode():
            logits = loaded.model(**inputs).logits
        assert torch.isfinite(logits).all()
        del logits, inputs
        chunks = [chunk async for chunk in provider.stream(_request())]
        assert "".join(chunk.content for chunk in chunks).strip()
        assert chunks[-1].finish_reason in {"stop", "length"}

        first_chunk = asyncio.Event()

        async def consume() -> None:
            async for chunk in provider.stream(_request(256)):
                if chunk.content:
                    first_chunk.set()

        task = asyncio.create_task(consume())
        await asyncio.wait_for(first_chunk.wait(), timeout=60)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not [
            thread
            for thread in threading.enumerate()
            if thread.name == "base-qwen-stream"
        ]
        assert (await provider.generate(_request(4))).content.strip()
        await provider.close()
        assert torch.cuda.memory_allocated(0) < 64 * 1024 * 1024
        assert torch.cuda.memory_reserved(0) < 64 * 1024 * 1024

    asyncio.run(run())
