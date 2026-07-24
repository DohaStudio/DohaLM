from __future__ import annotations

import pytest
import torch
import torch.nn.functional as functional

from src.model import DohaLMTiny, ModelConfig, causal_language_modeling_loss


def config() -> ModelConfig:
    return ModelConfig(
        vocab_size=32, context_length=8, num_layers=1, hidden_size=16,
        num_heads=4, head_dim=4, ffn_size=32, dropout=0.0,
    )


def test_shifted_loss_matches_manual_cross_entropy():
    logits = torch.randn(2, 4, 7, requires_grad=True)
    labels = torch.tensor([[1, 2, 3, 4], [2, 3, 4, 5]])
    expected = functional.cross_entropy(logits[:, :-1].contiguous().view(-1, 7), labels[:, 1:].contiguous().view(-1))
    actual = causal_language_modeling_loss(logits, labels)
    assert torch.allclose(actual, expected)


def test_model_supports_labels_equal_to_input_ids():
    model = DohaLMTiny(config())
    input_ids = torch.randint(0, 32, (2, 6))
    output = model(input_ids, labels=input_ids)
    assert output.loss is not None and output.loss.ndim == 0


def test_ignore_index_excludes_shifted_targets():
    logits = torch.randn(1, 4, 5)
    labels = torch.tensor([[0, 1, -100, 3]])
    actual = causal_language_modeling_loss(logits, labels)
    expected = functional.cross_entropy(logits[:, :-1].reshape(-1, 5), labels[:, 1:].reshape(-1), ignore_index=-100)
    assert torch.allclose(actual, expected)


def test_custom_ignore_index_is_supported():
    logits = torch.randn(1, 3, 5)
    labels = torch.tensor([[0, -7, 2]])
    assert torch.isfinite(causal_language_modeling_loss(logits, labels, ignore_index=-7))


def test_sequence_length_one_with_labels_fails_clearly():
    with pytest.raises(ValueError, match="SEQUENCE_TOO_SHORT_FOR_LOSS"):
        DohaLMTiny(config())(torch.tensor([[1]]), labels=torch.tensor([[1]]))


def test_sequence_length_one_without_labels_returns_logits():
    output = DohaLMTiny(config())(torch.tensor([[1]]))
    assert output.logits.shape == (1, 1, 32) and output.loss is None


def test_all_shifted_labels_ignored_fails_clearly():
    logits = torch.randn(1, 3, 5)
    with pytest.raises(ValueError, match="ALL_LABELS_IGNORED"):
        causal_language_modeling_loss(logits, torch.tensor([[1, -100, -100]]))


@pytest.mark.parametrize("labels,code", [
    (torch.ones(1, 2, dtype=torch.long), "LABELS_SHAPE_MISMATCH"),
    (torch.ones(1, 3, dtype=torch.int32), "LABELS_INVALID_DTYPE"),
    (torch.tensor([[0, -1, 2]]), "LABEL_TOKEN_OUT_OF_RANGE"),
    (torch.tensor([[0, 5, 2]]), "LABEL_TOKEN_OUT_OF_RANGE"),
])
def test_invalid_labels_fail_with_stable_code(labels, code):
    with pytest.raises(ValueError, match=code):
        causal_language_modeling_loss(torch.randn(1, 3, 5), labels)


def test_loss_backward_is_finite_for_logits_and_model_parameters():
    model = DohaLMTiny(config())
    input_ids = torch.randint(0, 32, (2, 6))
    loss = model(input_ids, labels=input_ids).loss
    assert loss is not None
    loss.backward()
    assert torch.isfinite(loss)
    assert all(parameter.grad is None or torch.isfinite(parameter.grad).all() for parameter in model.parameters())
