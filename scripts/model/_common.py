"""Shared bounded configuration for model smoke commands."""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from typing import Any

import torch

from src.model import ModelConfig


def smoke_config() -> ModelConfig:
    return ModelConfig(
        vocab_size=128,
        context_length=16,
        num_layers=2,
        hidden_size=32,
        num_heads=4,
        head_dim=8,
        ffn_size=64,
        dropout=0.0,
        layer_norm_eps=1e-5,
    )


def resolve_device_and_dtype(args: Namespace) -> tuple[torch.device, torch.dtype]:
    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA를 사용할 수 없습니다.")
    dtype = {"float32": torch.float32, "float16": torch.float16}[args.dtype]
    if device.type == "cpu" and dtype == torch.float16:
        raise ValueError("CPU float16 smoke는 지원하지 않습니다. float32를 사용하세요.")
    return device, dtype


def print_result(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def cli_error(exc: Exception) -> int:
    print(f"오류: {exc}", file=sys.stderr)
    return 2
