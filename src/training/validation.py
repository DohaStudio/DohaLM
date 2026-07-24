"""Independent no-gradient validation loop for causal language modeling."""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass

import torch
from torch import nn
from torch.utils.data import DataLoader

from .errors import TrainingError


@dataclass(frozen=True)
class ValidationResult:
    loss: float
    perplexity: float | None
    perplexity_status: str
    target_tokens: int
    batches: int
    sequences: int
    elapsed_seconds: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_language_model(model: nn.Module, dataloader: DataLoader, *, device: torch.device, use_amp: bool) -> ValidationResult:
    if len(dataloader) == 0:
        raise TrainingError("EMPTY_DATASET", "validation DataLoader가 비어 있습니다.")
    was_training = model.training
    total_nll = 0.0
    total_targets = 0
    batches = 0
    sequences = 0
    started = time.perf_counter()
    model.eval()
    try:
        with torch.no_grad():
            for batch in dataloader:
                moved = {name: tensor.to(device) for name, tensor in batch.items()}
                with torch.amp.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp and device.type == "cuda"):
                    output = model(moved["input_ids"], attention_mask=moved["attention_mask"], labels=moved["labels"])
                if output.loss is None or not bool(torch.isfinite(output.loss).item()):
                    raise TrainingError("NON_FINITE_LOSS", "validation loss가 유한하지 않습니다.")
                targets = int((moved["labels"][:, 1:] != -100).sum().item())
                total_nll += float(output.loss.detach().float().cpu().item()) * targets
                total_targets += targets
                batches += 1
                sequences += int(moved["input_ids"].shape[0])
    finally:
        model.train(was_training)
    if total_targets == 0:
        raise TrainingError("EMPTY_DATASET", "validation에 유효한 target token이 없습니다.")
    loss = total_nll / total_targets
    if loss > math.log(float.fromhex("0x1.fffffffffffffp+1023")):
        perplexity, status = None, "overflow"
    else:
        perplexity, status = math.exp(loss), "finite"
    return ValidationResult(loss, perplexity, status, total_targets, batches, sequences, time.perf_counter() - started)
