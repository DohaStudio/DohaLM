from __future__ import annotations

import pytest
import torch
from torch import nn

from src.model import (
    CausalMultiHeadAttention,
    FeedForward,
    LayerNorm,
    LearnedPositionEmbedding,
    LMHead,
    ModelConfig,
    ParameterCounter,
    TokenEmbedding,
    TransformerBlock,
)


def small_config(**changes) -> ModelConfig:
    values = {
        "vocab_size": 32,
        "context_length": 8,
        "num_layers": 2,
        "hidden_size": 16,
        "num_heads": 4,
        "head_dim": 4,
        "ffn_size": 64,
        "dropout": 0.0,
        "layer_norm_eps": 1e-5,
    }
    values.update(changes)
    return ModelConfig(**values)


def test_tiny_config_defaults_match_approved_architecture():
    config = ModelConfig()
    assert (
        config.vocab_size,
        config.context_length,
        config.num_layers,
        config.hidden_size,
        config.num_heads,
        config.head_dim,
        config.ffn_size,
    ) == (16_000, 256, 6, 384, 6, 64, 1_536)
    assert config.linear_bias is True
    assert config.lm_head_bias is False
    assert config.tie_word_embeddings is True
    assert config.initialization is None


def test_config_round_trip_dictionary_is_stable():
    config = small_config()
    assert ModelConfig(**config.to_dict()) == config


@pytest.mark.parametrize(("changes", "message"), [
    ({"vocab_size": 8}, "special token"),
    ({"context_length": 0}, "context_length"),
    ({"num_layers": 0}, "num_layers"),
    ({"hidden_size": 15}, "divisible"),
    ({"head_dim": 3}, "head_dim"),
    ({"dropout": -0.1}, "dropout"),
    ({"dropout": 1.0}, "dropout"),
    ({"dropout": True}, "dropout"),
    ({"layer_norm_eps": 0.0}, "layer_norm_eps"),
    ({"linear_bias": False}, "linear_bias"),
    ({"lm_head_bias": True}, "lm_head_bias"),
    ({"tie_word_embeddings": False}, "tie_word_embeddings"),
    ({"initialization": "gpt2"}, "initialization"),
])
def test_invalid_config_is_rejected(changes, message):
    with pytest.raises(ValueError, match=message):
        small_config(**changes)


def test_token_embedding_shape_dtype_device_and_parameter_count():
    config = small_config()
    module = TokenEmbedding(config)
    token_ids = torch.tensor([[0, 1, 31], [2, 3, 4]], dtype=torch.long)
    output = module(token_ids)
    assert output.shape == (2, 3, 16)
    assert output.dtype == module.weight.dtype
    assert output.device == module.weight.device
    assert module.weight.numel() == 32 * 16


@pytest.mark.parametrize("token_id", [-1, 32])
def test_token_embedding_rejects_out_of_range_ids(token_id):
    with pytest.raises(ValueError, match="vocabulary"):
        TokenEmbedding(small_config())(torch.tensor([[token_id]], dtype=torch.long))


@pytest.mark.parametrize("value", [torch.ones(2, dtype=torch.long), torch.ones(1, 2, 1, dtype=torch.long)])
def test_token_embedding_rejects_invalid_rank(value):
    with pytest.raises(ValueError, match="rank 2"):
        TokenEmbedding(small_config())(value)


def test_token_embedding_rejects_invalid_dtype_and_long_sequence():
    module = TokenEmbedding(small_config())
    with pytest.raises(TypeError, match="torch.long"):
        module(torch.ones((1, 2), dtype=torch.int32))
    with pytest.raises(ValueError, match="context_length"):
        module(torch.zeros((1, 9), dtype=torch.long))


def test_position_embedding_generates_zero_based_positions_and_broadcasts_batch():
    config = small_config()
    module = LearnedPositionEmbedding(config)
    token_ids = torch.tensor([[3, 3, 3], [7, 7, 7]], dtype=torch.long)
    positions = module.position_ids(token_ids)
    output = module(token_ids)
    assert torch.equal(positions, torch.tensor([0, 1, 2]))
    assert output.shape == (2, 3, 16)
    assert torch.equal(output[0], output[1])
    assert module.weight.numel() == 8 * 16


def test_position_embedding_rejects_sequence_over_context():
    with pytest.raises(ValueError, match="context_length"):
        LearnedPositionEmbedding(small_config())(torch.zeros((1, 9), dtype=torch.long))


def test_layer_norm_preserves_shape_dtype_and_has_affine_parameters():
    module = LayerNorm(16, 1e-5)
    inputs = torch.randn(2, 3, 16)
    output = module(inputs)
    assert output.shape == inputs.shape
    assert output.dtype == inputs.dtype
    assert sum(parameter.numel() for parameter in module.parameters()) == 32
    assert torch.allclose(output.mean(dim=-1), torch.zeros(2, 3), atol=1e-6)


def test_layer_norm_backward_is_finite():
    module = LayerNorm(16, 1e-5)
    inputs = torch.randn(2, 3, 16, requires_grad=True)
    module(inputs).square().mean().backward()
    assert inputs.grad is not None and torch.isfinite(inputs.grad).all()
    assert all(parameter.grad is not None and torch.isfinite(parameter.grad).all() for parameter in module.parameters())


@pytest.mark.parametrize("value,error", [
    (torch.ones(16), ValueError),
    (torch.ones(2, 3, 15), ValueError),
    (torch.ones(2, 3, 16, dtype=torch.long), TypeError),
])
def test_layer_norm_rejects_invalid_inputs(value, error):
    with pytest.raises(error):
        LayerNorm(16, 1e-5)(value)


def test_attention_shapes_projection_and_parameter_count():
    config = ModelConfig()
    module = CausalMultiHeadAttention(config)
    output = module(torch.randn(2, 4, config.hidden_size))
    assert output.shape == (2, 4, config.hidden_size)
    assert module.qkv_projection.weight.shape == (3 * config.hidden_size, config.hidden_size)
    assert module.causal_mask.shape == (1, 1, config.context_length, config.context_length)
    assert sum(parameter.numel() for parameter in module.parameters()) == 591_360


def test_attention_actual_output_cannot_observe_future_tokens():
    torch.manual_seed(7)
    module = CausalMultiHeadAttention(small_config()).eval()
    original = torch.randn(1, 5, 16)
    changed = original.clone()
    changed[:, 3:, :] = torch.randn_like(changed[:, 3:, :]) * 100
    with torch.no_grad():
        first = module(original)
        second = module(changed)
    assert torch.allclose(first[:, :3], second[:, :3], atol=1e-6, rtol=1e-5)
    assert not torch.allclose(first[:, 4], second[:, 4])


def test_attention_padding_mask_blocks_masked_keys_and_zeroes_masked_queries():
    torch.manual_seed(11)
    module = CausalMultiHeadAttention(small_config()).eval()
    inputs = torch.randn(1, 4, 16)
    changed = inputs.clone()
    changed[:, 2:, :] = 999
    mask = torch.tensor([[True, True, False, False]])
    with torch.no_grad():
        first = module(inputs, padding_mask=mask)
        second = module(changed, padding_mask=mask)
    assert torch.allclose(first[:, :2], second[:, :2], atol=1e-6)
    assert torch.count_nonzero(first[:, 2:]) == 0
    assert torch.count_nonzero(second[:, 2:]) == 0


@pytest.mark.parametrize("mask,error", [
    (torch.ones(1, 3, dtype=torch.bool), ValueError),
    (torch.ones(2, 4, 1, dtype=torch.bool), ValueError),
    (torch.ones(2, 4, dtype=torch.float32), TypeError),
])
def test_attention_rejects_invalid_padding_mask(mask, error):
    with pytest.raises(error):
        CausalMultiHeadAttention(small_config())(torch.randn(2, 4, 16), padding_mask=mask)


@pytest.mark.parametrize("value,error", [
    (torch.randn(2, 16), ValueError),
    (torch.randn(2, 3, 15), ValueError),
    (torch.ones(2, 3, 16, dtype=torch.long), TypeError),
    (torch.randn(1, 9, 16), ValueError),
])
def test_attention_rejects_invalid_hidden_states(value, error):
    with pytest.raises(error):
        CausalMultiHeadAttention(small_config())(value)


def test_attention_backward_gradients_are_finite():
    module = CausalMultiHeadAttention(small_config())
    inputs = torch.randn(2, 4, 16, requires_grad=True)
    module(inputs).square().mean().backward()
    assert inputs.grad is not None and torch.isfinite(inputs.grad).all()
    assert all(parameter.grad is not None and torch.isfinite(parameter.grad).all() for parameter in module.parameters())


def test_attention_eval_is_deterministic():
    module = CausalMultiHeadAttention(small_config(dropout=0.25)).eval()
    inputs = torch.randn(2, 4, 16)
    assert torch.equal(module(inputs), module(inputs))


def test_feed_forward_shape_gelu_parameters_and_backward():
    config = ModelConfig()
    module = FeedForward(config)
    inputs = torch.randn(1, 3, config.hidden_size, requires_grad=True)
    output = module(inputs)
    output.mean().backward()
    assert output.shape == inputs.shape
    assert isinstance(module.activation, nn.GELU)
    assert sum(parameter.numel() for parameter in module.parameters()) == 1_181_568
    assert inputs.grad is not None and torch.isfinite(inputs.grad).all()


@pytest.mark.parametrize("value,error", [
    (torch.randn(2, 16), ValueError),
    (torch.randn(2, 3, 15), ValueError),
    (torch.ones(2, 3, 16, dtype=torch.long), TypeError),
])
def test_feed_forward_rejects_invalid_inputs(value, error):
    with pytest.raises(error):
        FeedForward(small_config())(value)


def test_transformer_block_shape_parameter_count_and_finite_backward():
    config = ModelConfig()
    module = TransformerBlock(config)
    inputs = torch.randn(1, 3, config.hidden_size, requires_grad=True)
    output = module(inputs)
    output.square().mean().backward()
    assert output.shape == inputs.shape
    assert sum(parameter.numel() for parameter in module.parameters()) == 1_774_464
    assert inputs.grad is not None and torch.isfinite(inputs.grad).all()


def test_transformer_block_uses_pre_layer_norm_and_eval_is_deterministic():
    module = TransformerBlock(small_config(dropout=0.4)).eval()
    captured = []

    def capture_attention(_module, args):
        captured.append(args[0].detach())

    handle = module.attention.register_forward_pre_hook(capture_attention)
    inputs = torch.randn(2, 4, 16)
    first = module(inputs)
    second = module(inputs)
    handle.remove()
    assert torch.equal(first, second)
    assert torch.allclose(captured[0].mean(dim=-1), torch.zeros(2, 4), atol=1e-5)


def test_lm_head_shape_has_no_bias_and_ties_same_parameter_storage():
    config = small_config()
    embedding = TokenEmbedding(config)
    head = LMHead(config, embedding)
    logits = head(torch.randn(2, 3, 16))
    assert logits.shape == (2, 3, 32)
    assert head.projection.bias is None
    assert head.weight is embedding.weight
    assert head.weight.data_ptr() == embedding.weight.data_ptr()


def test_lm_head_rejects_weight_tying_shape_mismatch_and_invalid_type():
    config = small_config()
    head = LMHead(config)
    with pytest.raises(ValueError, match="shape"):
        head.tie_weights(nn.Embedding(31, 16))
    with pytest.raises(TypeError, match="token_embedding"):
        head.tie_weights(nn.Linear(16, 32))  # type: ignore[arg-type]


@pytest.mark.parametrize("value,error", [
    (torch.randn(2, 16), ValueError),
    (torch.randn(2, 3, 15), ValueError),
    (torch.ones(2, 3, 16, dtype=torch.long), TypeError),
])
def test_lm_head_rejects_invalid_hidden_states(value, error):
    with pytest.raises(error):
        LMHead(small_config())(value)


class TinyComponentSet(nn.Module):
    """Count-only container; it intentionally has no integrated forward."""

    def __init__(self, config: ModelConfig):
        super().__init__()
        self.token_embedding = TokenEmbedding(config)
        self.position_embedding = LearnedPositionEmbedding(config)
        self.blocks = nn.ModuleList([TransformerBlock(config) for _ in range(config.num_layers)])
        self.final_norm = LayerNorm(config.hidden_size, config.layer_norm_eps)
        self.lm_head = LMHead(config, self.token_embedding)


def test_parameter_counter_matches_approved_tiny_total_and_excludes_tied_weight():
    config = ModelConfig()
    modules = TinyComponentSet(config)
    count = ParameterCounter.count(modules)
    assert ParameterCounter.expected_tiny_total(config) == 16_889_856
    assert count.total == 16_889_856
    assert count.trainable == 16_889_856
    assert count.tied_references_excluded == 6_144_000
    assert sum(count.by_module.values()) == count.total


def test_parameter_counter_reports_frozen_and_module_counts():
    module = nn.Sequential(nn.Linear(3, 4), nn.Linear(4, 2, bias=False))
    module[1].weight.requires_grad_(False)
    count = ParameterCounter.count(module)
    assert count.total == 24
    assert count.trainable == 16
    assert count.by_module == {"0": 16, "1": 8}


def test_parameter_counter_rejects_non_module():
    with pytest.raises(TypeError, match="torch.nn.Module"):
        ParameterCounter.count(object())  # type: ignore[arg-type]


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_cuda_fp16_component_forward_backward_is_finite():
    device = torch.device("cuda")
    config = small_config()
    token_embedding = TokenEmbedding(config).to(device)
    position_embedding = LearnedPositionEmbedding(config).to(device)
    block = TransformerBlock(config).to(device=device, dtype=torch.float16)
    head = LMHead(config, token_embedding).to(device=device, dtype=torch.float16)
    token_ids = torch.tensor([[1, 2, 3, 4]], device=device, dtype=torch.long)
    hidden = (token_embedding(token_ids) + position_embedding(token_ids)).to(torch.float16)
    logits = head(block(hidden))
    logits.float().square().mean().backward()
    assert logits.shape == (1, 4, 32)
    gradients = [parameter.grad for parameter in (list(block.parameters()) + list(head.parameters())) if parameter.requires_grad]
    assert gradients and all(gradient is not None and torch.isfinite(gradient).all() for gradient in gradients)
