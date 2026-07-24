from __future__ import annotations

from types import SimpleNamespace

import pytest
import torch
from torch import nn

from src.model import DohaLMTiny, DohaLMOutput, ModelConfig, greedy_generate


def config() -> ModelConfig:
    return ModelConfig(
        vocab_size=32, context_length=10, num_layers=1, hidden_size=16,
        num_heads=4, head_dim=4, ffn_size=32, dropout=0.0,
    )


def test_greedy_generation_is_deterministic_and_preserves_prefix():
    torch.manual_seed(5)
    model = DohaLMTiny(config())
    prefix = torch.tensor([[1, 2, 3], [4, 5, 6]])
    first = model.generate(prefix, max_new_tokens=3)
    second = model.generate(prefix, max_new_tokens=3)
    assert torch.equal(first, second)
    assert first.shape == (2, 6)
    assert torch.equal(first[:, :3], prefix)
    assert bool(((first >= 0) & (first < 32)).all())


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_generation_rejects_invalid_max_new_tokens(value):
    with pytest.raises(ValueError, match="MAX_NEW_TOKENS_INVALID"):
        DohaLMTiny(config()).generate(torch.tensor([[1, 2]]), max_new_tokens=value)  # type: ignore[arg-type]


def test_generation_rejects_context_overflow_without_truncation():
    with pytest.raises(ValueError, match="GENERATION_CONTEXT_EXCEEDED"):
        DohaLMTiny(config()).generate(torch.ones(1, 9, dtype=torch.long), max_new_tokens=2)


@pytest.mark.parametrize("eos", [-1, 32, True])
def test_generation_rejects_invalid_eos(eos):
    with pytest.raises(ValueError, match="EOS_TOKEN"):
        DohaLMTiny(config()).generate(torch.tensor([[1, 2]]), max_new_tokens=1, eos_token_id=eos)


def test_generation_restores_original_train_mode_and_has_no_grad():
    model = DohaLMTiny(config()).train()
    generated = model.generate(torch.tensor([[1, 2]]), max_new_tokens=2)
    assert model.training is True
    assert generated.requires_grad is False
    model.eval()
    model.generate(torch.tensor([[1, 2]]), max_new_tokens=1)
    assert model.training is False


class ScriptedModel(nn.Module):
    def __init__(self, scripts: list[list[int]], *, vocab_size: int = 8, context_length: int = 8):
        super().__init__()
        self.config = SimpleNamespace(vocab_size=vocab_size, context_length=context_length)
        self.scripts = scripts
        self.steps = 0
        self.grad_enabled: list[bool] = []
        self.mask_shapes: list[tuple[int, ...] | None] = []

    def forward(self, input_ids, *, attention_mask=None):
        self.grad_enabled.append(torch.is_grad_enabled())
        self.mask_shapes.append(tuple(attention_mask.shape) if attention_mask is not None else None)
        logits = torch.full((input_ids.shape[0], input_ids.shape[1], self.config.vocab_size), -100.0)
        for row, script in enumerate(self.scripts):
            token = script[min(self.steps, len(script) - 1)]
            logits[row, -1, token] = 100.0
        self.steps += 1
        return DohaLMOutput(logits=logits)


def test_eos_immediately_stops_single_batch():
    model = ScriptedModel([[3, 4]])
    output = greedy_generate(model, torch.tensor([[1, 2]]), max_new_tokens=4, eos_token_id=3)
    assert output.tolist() == [[1, 2, 3]]
    assert model.steps == 1


def test_batch_rows_finish_independently_and_finished_rows_repeat_eos():
    model = ScriptedModel([[3, 7], [4, 3]])
    output = greedy_generate(model, torch.tensor([[1], [2]]), max_new_tokens=4, eos_token_id=3)
    assert output.tolist() == [[1, 3, 3], [2, 4, 3]]


def test_generation_expands_attention_mask_and_runs_under_no_grad():
    model = ScriptedModel([[4, 5]])
    mask = torch.tensor([[True, True]])
    output = greedy_generate(model, torch.tensor([[1, 2]]), max_new_tokens=2, attention_mask=mask)
    assert output.shape == (1, 4)
    assert model.mask_shapes == [(1, 2), (1, 3)]
    assert model.grad_enabled == [False, False]


@pytest.mark.parametrize("mask,code", [
    (torch.ones(1, 3, dtype=torch.bool), "ATTENTION_MASK_SHAPE_MISMATCH"),
    (torch.ones(1, 2), "ATTENTION_MASK_INVALID_DTYPE"),
])
def test_generation_rejects_invalid_attention_mask(mask, code):
    with pytest.raises(ValueError, match=code):
        greedy_generate(ScriptedModel([[1]]), torch.tensor([[1, 2]]), max_new_tokens=1, attention_mask=mask)
