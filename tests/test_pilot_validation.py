from __future__ import annotations

import torch

from src.model import DohaLMTiny, ModelConfig
from src.training import CausalLMCollator, SyntheticTokenDataset, TrainingConfig, create_dataloader, evaluate_language_model


def test_validation_is_no_grad_and_restores_training_mode():
    model_config = ModelConfig(vocab_size=32, context_length=8, num_layers=1, hidden_size=16, num_heads=4, head_dim=4, ffn_size=32)
    model = DohaLMTiny(model_config)
    dataset = SyntheticTokenDataset(vocab_size=32, sequence_length=5, num_records=4, pattern=[2, 8, 9, 10, 3])
    training = TrainingConfig(max_steps=1, save_every=1, output_dir="tests/output/validation")
    loader = create_dataloader(dataset, CausalLMCollator(context_length=8), training, shuffle=False)
    model.train()
    result = evaluate_language_model(model, loader, device=torch.device("cpu"), use_amp=False)
    assert result.loss > 0 and result.perplexity is not None and result.target_tokens > 0
    assert model.training
    assert all(parameter.grad is None for parameter in model.parameters())


def test_validation_is_deterministic_in_eval_mode():
    model_config = ModelConfig(vocab_size=32, context_length=8, num_layers=1, hidden_size=16, num_heads=4, head_dim=4, ffn_size=32)
    model = DohaLMTiny(model_config)
    dataset = SyntheticTokenDataset(vocab_size=32, sequence_length=5, num_records=2, pattern=[2, 8, 9, 10, 3])
    training = TrainingConfig(max_steps=1, save_every=1, output_dir="tests/output/validation")
    loader = create_dataloader(dataset, CausalLMCollator(context_length=8), training, shuffle=False)
    first = evaluate_language_model(model, loader, device=torch.device("cpu"), use_amp=False)
    second = evaluate_language_model(model, loader, device=torch.device("cpu"), use_amp=False)
    assert first.loss == second.loss
    assert first.perplexity == second.perplexity
    assert first.target_tokens == second.target_tokens
    assert first.sequences == second.sequences
