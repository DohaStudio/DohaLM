from __future__ import annotations

import torch
from torch import nn

from src.training import CudaMemoryProbe, module_gradient_bytes, module_parameter_bytes, optimizer_state_bytes


def test_cpu_memory_probe_reports_unsupported() -> None:
    model = nn.Linear(2, 2)
    report = CudaMemoryProbe("cpu").finish(model=model, optimizer=torch.optim.AdamW(model.parameters()))
    assert report.supported is False
    assert report.peak_allocated_bytes == 0


def test_parameter_bytes_use_tensor_element_size() -> None:
    model = nn.Linear(2, 3, bias=False)
    assert module_parameter_bytes(model) == 6 * model.weight.element_size()


def test_gradient_bytes_are_zero_before_backward() -> None:
    assert module_gradient_bytes(nn.Linear(2, 2)) == 0


def test_optimizer_state_bytes_after_step() -> None:
    model = nn.Linear(2, 2)
    optimizer = torch.optim.AdamW(model.parameters())
    model(torch.ones(1, 2)).sum().backward()
    optimizer.step()
    assert optimizer_state_bytes(optimizer) > 0


def test_cuda_probe_calls_reset_and_synchronize(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "synchronize", lambda device=None: calls.append("sync"))
    monkeypatch.setattr(torch.cuda, "reset_peak_memory_stats", lambda device=None: calls.append("reset"))
    monkeypatch.setattr(torch.cuda, "max_memory_allocated", lambda device=None: 11)
    monkeypatch.setattr(torch.cuda, "max_memory_reserved", lambda device=None: 22)
    monkeypatch.setattr(torch.cuda, "memory_allocated", lambda device=None: 3)
    monkeypatch.setattr(torch.cuda, "memory_reserved", lambda device=None: 4)
    model = nn.Linear(2, 2)
    optimizer = torch.optim.AdamW(model.parameters())
    probe = CudaMemoryProbe("cuda")
    probe.start()
    report = probe.finish(model=model, optimizer=optimizer)
    assert calls == ["sync", "reset", "sync"]
    assert (report.peak_allocated_bytes, report.peak_reserved_bytes) == (11, 22)
