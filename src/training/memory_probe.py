"""CUDA memory measurement helpers for bounded Tiny validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import torch
from torch import nn


def module_parameter_bytes(module: nn.Module) -> int:
    return sum(parameter.numel() * parameter.element_size() for parameter in module.parameters())


def module_gradient_bytes(module: nn.Module) -> int:
    return sum(
        parameter.grad.numel() * parameter.grad.element_size()
        for parameter in module.parameters()
        if parameter.grad is not None
    )


def optimizer_state_bytes(optimizer: torch.optim.Optimizer) -> int:
    total = 0
    for state in optimizer.state.values():
        for value in state.values():
            if isinstance(value, torch.Tensor):
                total += value.numel() * value.element_size()
    return total


@dataclass(frozen=True)
class MemorySnapshot:
    supported: bool
    peak_allocated_bytes: int
    peak_reserved_bytes: int
    allocated_after_step_bytes: int
    reserved_after_step_bytes: int
    model_parameter_bytes: int
    optimizer_state_bytes: int
    gradient_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CudaMemoryProbe:
    def __init__(self, device: torch.device | str) -> None:
        self.device = torch.device(device)

    @property
    def supported(self) -> bool:
        return self.device.type == "cuda" and torch.cuda.is_available()

    def start(self) -> None:
        if not self.supported:
            return
        torch.cuda.synchronize(self.device)
        torch.cuda.reset_peak_memory_stats(self.device)

    def finish(self, *, model: nn.Module, optimizer: torch.optim.Optimizer) -> MemorySnapshot:
        if not self.supported:
            return MemorySnapshot(False, 0, 0, 0, 0, module_parameter_bytes(model), optimizer_state_bytes(optimizer), module_gradient_bytes(model))
        torch.cuda.synchronize(self.device)
        return MemorySnapshot(
            supported=True,
            peak_allocated_bytes=torch.cuda.max_memory_allocated(self.device),
            peak_reserved_bytes=torch.cuda.max_memory_reserved(self.device),
            allocated_after_step_bytes=torch.cuda.memory_allocated(self.device),
            reserved_after_step_bytes=torch.cuda.memory_reserved(self.device),
            model_parameter_bytes=module_parameter_bytes(model),
            optimizer_state_bytes=optimizer_state_bytes(optimizer),
            gradient_bytes=module_gradient_bytes(model),
        )
