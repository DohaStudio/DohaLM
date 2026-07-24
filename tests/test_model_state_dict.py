from __future__ import annotations

import pytest
import torch

from src.model import DohaLMTiny, ModelConfig


def config(**changes) -> ModelConfig:
    values = {
        "vocab_size": 32, "context_length": 8, "num_layers": 1,
        "hidden_size": 16, "num_heads": 4, "head_dim": 4,
        "ffn_size": 32, "dropout": 0.0,
    }
    values.update(changes)
    return ModelConfig(**values)


def test_state_bundle_round_trip_preserves_logits_and_tying():
    torch.manual_seed(7)
    source = DohaLMTiny(config()).eval()
    input_ids = torch.tensor([[1, 2, 3, 4]])
    expected = source(input_ids).logits.detach().clone()
    restored = DohaLMTiny(config()).eval()
    restored.load_state_dict_with_config(source.state_dict_with_config())
    assert torch.equal(expected, restored(input_ids).logits)
    assert restored.token_embedding.weight is restored.lm_head.weight


def test_direct_state_dict_round_trip_keeps_constructor_tying():
    source = DohaLMTiny(config())
    restored = DohaLMTiny(config())
    restored.load_state_dict(source.state_dict())
    assert restored.token_embedding.weight is restored.lm_head.weight
    assert restored.token_embedding.weight.data_ptr() == restored.lm_head.weight.data_ptr()


def test_state_bundle_rejects_config_mismatch():
    payload = DohaLMTiny(config()).state_dict_with_config()
    with pytest.raises(ValueError, match="MODEL_CONFIG_MISMATCH"):
        DohaLMTiny(config(context_length=9)).load_state_dict_with_config(payload)


def test_state_bundle_rejects_missing_key_clearly():
    model = DohaLMTiny(config())
    payload = model.state_dict_with_config()
    payload["state_dict"].pop("final_norm.bias")
    with pytest.raises(ValueError, match="STATE_DICT_INCOMPATIBLE") as exc_info:
        DohaLMTiny(config()).load_state_dict_with_config(payload)
    assert "Missing key" in str(exc_info.value)


def test_state_bundle_rejects_unexpected_key_clearly():
    payload = DohaLMTiny(config()).state_dict_with_config()
    payload["state_dict"]["unexpected.weight"] = torch.ones(1)
    with pytest.raises(ValueError, match="STATE_DICT_INCOMPATIBLE") as exc_info:
        DohaLMTiny(config()).load_state_dict_with_config(payload)
    assert "Unexpected key" in str(exc_info.value)


def test_same_seed_produces_same_initial_state_and_different_seed_changes_it():
    torch.manual_seed(11)
    first = DohaLMTiny(config())
    torch.manual_seed(11)
    second = DohaLMTiny(config())
    torch.manual_seed(12)
    third = DohaLMTiny(config())
    assert all(torch.equal(a, b) for a, b in zip(first.parameters(), second.parameters()))
    assert any(not torch.equal(a, b) for a, b in zip(first.parameters(), third.parameters()))


def test_initial_parameters_are_finite_and_no_padding_idx_is_added():
    model = DohaLMTiny(config())
    assert model.token_embedding.embedding.padding_idx is None
    assert all(torch.isfinite(parameter).all() for parameter in model.parameters())


def test_model_parameter_iterator_contains_no_tied_duplicate_object():
    model = DohaLMTiny(config())
    identities = [id(parameter) for parameter in model.parameters()]
    assert len(identities) == len(set(identities))


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_cpu_state_bundle_loads_into_cuda_model_and_preserves_tying():
    source = DohaLMTiny(config())
    payload = source.state_dict_with_config()
    restored = DohaLMTiny(config()).cuda()
    restored.load_state_dict_with_config(payload)
    assert restored.token_embedding.weight.device.type == "cuda"
    assert restored.token_embedding.weight is restored.lm_head.weight
