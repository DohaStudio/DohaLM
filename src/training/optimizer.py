"""AdamW parameter groups with tied-parameter deduplication."""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn

from src.model.layer_norm import LayerNorm

from .config import TrainingConfig
from .errors import TrainingError


@dataclass(frozen=True)
class OptimizerStats:
    decay_parameter_count: int
    no_decay_parameter_count: int
    unique_trainable_parameter_count: int
    parameter_group_count: int

    def to_dict(self) -> dict[str, int]:
        return self.__dict__.copy()


def create_optimizer(model: nn.Module, config: TrainingConfig) -> tuple[torch.optim.AdamW, OptimizerStats]:
    decay: list[nn.Parameter] = []
    no_decay: list[nn.Parameter] = []
    seen: set[int] = set()
    for module_name, module in model.named_modules():
        for parameter_name, parameter in module.named_parameters(recurse=False):
            if not parameter.requires_grad or id(parameter) in seen:
                continue
            seen.add(id(parameter))
            full_name = f"{module_name}.{parameter_name}" if module_name else parameter_name
            if parameter_name == "bias" or isinstance(module, (LayerNorm, nn.LayerNorm)):
                no_decay.append(parameter)
            else:
                decay.append(parameter)
    if not seen:
        raise TrainingError("INVALID_TRAINING_CONFIG", "학습 가능한 parameter가 없습니다.")
    groups = []
    if decay:
        groups.append({"params": decay, "weight_decay": config.weight_decay, "group_name": "decay"})
    if no_decay:
        groups.append({"params": no_decay, "weight_decay": 0.0, "group_name": "no_decay"})
    optimizer = torch.optim.AdamW(
        groups,
        lr=config.learning_rate,
        betas=config.betas,
        eps=config.epsilon,
    )
    decay_count = sum(parameter.numel() for parameter in decay)
    no_decay_count = sum(parameter.numel() for parameter in no_decay)
    return optimizer, OptimizerStats(decay_count, no_decay_count, decay_count + no_decay_count, len(groups))
