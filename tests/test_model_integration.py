from __future__ import annotations

import pytest
import torch

from src.model import DohaLMTiny, DohaLMOutput, ModelConfig


def small_config(**changes) -> ModelConfig:
    values = {
        "vocab_size": 128, "context_length": 16, "num_layers": 2,
        "hidden_size": 32, "num_heads": 4, "head_dim": 8,
        "ffn_size": 64, "dropout": 0.0, "layer_norm_eps": 1e-5,
    }
    values.update(changes)
    return ModelConfig(**values)


def test_default_model_constructs_approved_six_block_architecture():
    model = DohaLMTiny()
    assert model.config == ModelConfig()
    assert len(model.blocks) == 6
    assert model.token_embedding.weight is model.lm_head.weight
    assert model.final_norm.weight.shape == (384,)


def test_small_model_constructs_from_config():
    config = small_config()
    model = DohaLMTiny(config)
    assert model.config is config
    assert len(model.blocks) == 2


def test_forward_returns_explicit_output_logits_shape_dtype_and_device():
    model = DohaLMTiny(small_config())
    input_ids = torch.randint(0, 128, (2, 8))
    output = model(input_ids)
    assert isinstance(output, DohaLMOutput)
    assert output.logits.shape == (2, 8, 128)
    assert output.logits.is_floating_point()
    assert output.logits.device == input_ids.device
    assert output.loss is None
    assert output.hidden_states is None


def test_attention_mask_is_forwarded_and_padding_outputs_remain_finite():
    model = DohaLMTiny(small_config())
    input_ids = torch.randint(0, 128, (2, 6))
    mask = torch.tensor([[True, True, True, False, False, False], [True] * 6])
    output = model(input_ids, attention_mask=mask)
    assert output.logits.shape == (2, 6, 128)
    assert torch.isfinite(output.logits).all()


def test_hidden_states_are_opt_in_and_include_embedding_blocks_final_norm():
    model = DohaLMTiny(small_config())
    output = model(torch.randint(0, 128, (2, 5)), return_hidden_states=True)
    assert output.hidden_states is not None
    assert len(output.hidden_states) == 4
    assert all(value.shape == (2, 5, 32) for value in output.hidden_states)


def test_eval_forward_is_deterministic():
    model = DohaLMTiny(small_config(dropout=0.25)).eval()
    input_ids = torch.randint(0, 128, (2, 6))
    with torch.no_grad():
        first = model(input_ids).logits
        second = model(input_ids).logits
    assert torch.equal(first, second)


def test_integrated_causal_logits_cannot_observe_future_tokens():
    torch.manual_seed(3)
    model = DohaLMTiny(small_config()).eval()
    first_ids = torch.tensor([[1, 2, 3, 4, 5]])
    changed_ids = torch.tensor([[1, 2, 3, 91, 92]])
    with torch.no_grad():
        first = model(first_ids).logits
        changed = model(changed_ids).logits
    assert torch.allclose(first[:, :3], changed[:, :3], atol=1e-5, rtol=1e-5)
    assert not torch.allclose(first[:, 4], changed[:, 4])


def test_training_forward_loss_backward_has_finite_gradients():
    model = DohaLMTiny(small_config())
    input_ids = torch.randint(0, 128, (2, 8))
    output = model(input_ids, labels=input_ids)
    assert output.loss is not None and output.loss.ndim == 0
    output.loss.backward()
    gradients = [parameter.grad for parameter in model.parameters() if parameter.requires_grad]
    assert gradients and all(gradient is not None and torch.isfinite(gradient).all() for gradient in gradients)


@pytest.mark.parametrize("input_ids,error", [
    (torch.ones(4, dtype=torch.long), ValueError),
    (torch.ones(1, 4, dtype=torch.int32), TypeError),
    (torch.tensor([[128]], dtype=torch.long), ValueError),
    (torch.zeros(1, 17, dtype=torch.long), ValueError),
])
def test_forward_rejects_invalid_input_ids(input_ids, error):
    with pytest.raises(error):
        DohaLMTiny(small_config())(input_ids)


@pytest.mark.parametrize("mask,error_code", [
    (torch.ones(1, 3, dtype=torch.bool), "ATTENTION_MASK_SHAPE_MISMATCH"),
    (torch.ones(2, 4), "ATTENTION_MASK_INVALID_DTYPE"),
])
def test_forward_rejects_invalid_attention_mask(mask, error_code):
    with pytest.raises(ValueError, match=error_code):
        DohaLMTiny(small_config())(torch.ones(2, 4, dtype=torch.long), attention_mask=mask)


def test_forward_rejects_non_boolean_hidden_state_option():
    with pytest.raises(ValueError, match="RETURN_HIDDEN_STATES_INVALID"):
        DohaLMTiny(small_config())(
            torch.ones(1, 3, dtype=torch.long), return_hidden_states=1  # type: ignore[arg-type]
        )


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_cuda_fp32_integrated_forward_backward_and_generation():
    device = torch.device("cuda")
    model = DohaLMTiny(small_config()).to(device)
    input_ids = torch.randint(0, 128, (2, 8), device=device)
    output = model(input_ids, labels=input_ids)
    assert output.loss is not None and torch.isfinite(output.loss)
    output.loss.backward()
    assert all(parameter.grad is None or torch.isfinite(parameter.grad).all() for parameter in model.parameters())
    generated = model.generate(input_ids[:, :3], max_new_tokens=2)
    assert generated.shape == (2, 5) and generated.device.type == device.type


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_cuda_autocast_fp16_loss_and_gradients_are_finite():
    device = torch.device("cuda")
    model = DohaLMTiny(small_config()).to(device)
    input_ids = torch.randint(0, 128, (2, 8), device=device)
    with torch.autocast(device_type="cuda", dtype=torch.float16):
        output = model(input_ids, labels=input_ids)
    assert output.logits.dtype == torch.float16
    assert output.loss is not None and torch.isfinite(output.loss)
    output.loss.backward()
    assert all(parameter.grad is None or torch.isfinite(parameter.grad).all() for parameter in model.parameters())
