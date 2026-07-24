from __future__ import annotations

import pytest
import torch

from src.training import LinearWarmupDecayScheduler, TrainingError


def make_scheduler(*, warmup=2, maximum=6):
    parameter = torch.nn.Parameter(torch.ones(1))
    optimizer = torch.optim.AdamW([parameter], lr=0.01)
    return optimizer, LinearWarmupDecayScheduler(optimizer, warmup_steps=warmup, max_steps=maximum)


@pytest.mark.parametrize("step,factor", [(0, 0.0), (1, 0.5), (2, 1.0), (4, 0.5), (6, 0.0), (8, 0.0)])
def test_linear_warmup_decay_boundaries(step, factor):
    _, scheduler = make_scheduler()
    assert scheduler.factor(step) == pytest.approx(factor)


def test_scheduler_updates_optimizer_learning_rate():
    optimizer, scheduler = make_scheduler()
    assert optimizer.param_groups[0]["lr"] == 0.0
    scheduler.step()
    assert optimizer.param_groups[0]["lr"] == pytest.approx(0.005)
    scheduler.step()
    assert optimizer.param_groups[0]["lr"] == pytest.approx(0.01)


def test_no_warmup_starts_at_base_lr_and_never_negative():
    optimizer, scheduler = make_scheduler(warmup=0, maximum=2)
    assert optimizer.param_groups[0]["lr"] == pytest.approx(0.01)
    scheduler.step(); scheduler.step(); scheduler.step()
    assert optimizer.param_groups[0]["lr"] == 0.0


def test_scheduler_round_trip_continuity():
    first_optimizer, first = make_scheduler()
    first.step(); first.step(); first.step()
    state = first.state_dict()
    second_optimizer, second = make_scheduler()
    second.load_state_dict(state)
    assert second.current_step == first.current_step
    assert second_optimizer.param_groups[0]["lr"] == first_optimizer.param_groups[0]["lr"]
    first.step(); second.step()
    assert second.get_last_lr() == first.get_last_lr()


def test_scheduler_rejects_negative_step():
    _, scheduler = make_scheduler()
    with pytest.raises(TrainingError, match="음수"):
        scheduler.factor(-1)


def test_scheduler_rejects_incompatible_resume():
    _, first = make_scheduler(maximum=5)
    _, second = make_scheduler(maximum=6)
    with pytest.raises(TrainingError, match="RESUME_STATE_MISMATCH"):
        second.load_state_dict(first.state_dict())
