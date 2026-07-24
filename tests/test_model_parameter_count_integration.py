from __future__ import annotations

from src.model import DohaLMTiny, ModelConfig, ParameterCounter


def test_integrated_default_model_parameter_count_is_exact():
    model = DohaLMTiny()
    count = ParameterCounter.count(model)
    assert count.total == 16_889_856
    assert count.trainable == 16_889_856
    assert count.tied_references_excluded == 6_144_000


def test_integrated_parameter_breakdown_matches_approved_values():
    breakdown = DohaLMTiny().parameter_breakdown()
    assert breakdown == {
        "total_parameters": 16_889_856,
        "trainable_parameters": 16_889_856,
        "token_embedding": 6_144_000,
        "position_embedding": 98_304,
        "blocks": 10_646_784,
        "final_layer_norm": 768,
        "lm_head_unique": 0,
        "tied_parameter_count": 6_144_000,
    }


def test_integrated_count_matches_formula():
    config = ModelConfig()
    assert ParameterCounter.count(DohaLMTiny(config)).total == ParameterCounter.expected_tiny_total(config)


def test_small_model_count_matches_formula_and_is_trainable():
    config = ModelConfig(
        vocab_size=32, context_length=8, num_layers=1, hidden_size=16,
        num_heads=4, head_dim=4, ffn_size=32,
    )
    count = ParameterCounter.count(DohaLMTiny(config))
    assert count.total == ParameterCounter.expected_tiny_total(config)
    assert count.trainable == count.total


def test_lm_head_contributes_no_unique_parameter_when_tied():
    model = DohaLMTiny()
    assert model.parameter_breakdown()["lm_head_unique"] == 0
    assert model.token_embedding.weight is model.lm_head.weight
