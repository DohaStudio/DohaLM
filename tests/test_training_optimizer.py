from __future__ import annotations

import pytest
import torch
from _training_helpers import tiny_model_config, training_config
from torch import nn

from src.model import DohaLMTiny
from src.training import TrainingError, create_optimizer


def test_adamw_groups_decay_and_no_decay():
    model = DohaLMTiny(tiny_model_config())
    optimizer, stats = create_optimizer(model, training_config())
    assert isinstance(optimizer, torch.optim.AdamW)
    assert stats.parameter_group_count == 2
    assert {group["group_name"] for group in optimizer.param_groups} == {"decay", "no_decay"}
    assert sorted(group["weight_decay"] for group in optimizer.param_groups) == [0.0, 0.01]


def test_optimizer_counts_each_tied_parameter_once():
    model = DohaLMTiny(tiny_model_config())
    optimizer, stats = create_optimizer(model, training_config())
    unique_ids = {id(parameter) for group in optimizer.param_groups for parameter in group["params"]}
    assert stats.unique_trainable_parameter_count == model.parameter_breakdown()["total_parameters"]
    assert len(unique_ids) == sum(len(group["params"]) for group in optimizer.param_groups)
    assert model.token_embedding.weight is model.lm_head.weight


def test_bias_and_layer_norm_are_no_decay():
    model = DohaLMTiny(tiny_model_config())
    optimizer, stats = create_optimizer(model, training_config())
    no_decay = next(group for group in optimizer.param_groups if group["group_name"] == "no_decay")
    expected = sum(
        parameter.numel()
        for name, parameter in model.named_parameters()
        if name.endswith("bias") or "norm" in name
    )
    assert stats.no_decay_parameter_count == expected
    assert sum(parameter.numel() for parameter in no_decay["params"]) == expected


def test_frozen_parameters_are_excluded():
    model = DohaLMTiny(tiny_model_config())
    frozen = model.position_embedding.weight
    frozen.requires_grad_(False)
    _, stats = create_optimizer(model, training_config())
    assert stats.unique_trainable_parameter_count == model.parameter_breakdown()["total_parameters"] - frozen.numel()


def test_empty_trainable_parameters_are_rejected():
    model = nn.Linear(2, 2)
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    with pytest.raises(TrainingError, match="학습 가능한 parameter"):
        create_optimizer(model, training_config())
