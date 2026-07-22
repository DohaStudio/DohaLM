from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from src.config.errors import ConfigError, ConfigValidationError, DisabledConfigError
from src.config.loader import load_resolved_config, load_yaml, mask_secrets, parse_overrides
from src.config.validation import validate_model_config, validate_run_config
from src.runtime.paths import repository_root


@pytest.fixture
def tiny() -> dict:
    return load_yaml(repository_root() / "configs" / "tiny.yaml")


def test_tiny_config_matches_approved_invariants(tiny):
    validate_model_config(tiny, "tiny.yaml")
    assert tiny["expected_parameter_count"] == 16_889_856
    assert tiny["hidden_size"] == tiny["num_attention_heads"] * tiny["head_dim"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("head_dim", 32),
        ("num_attention_heads", 5),
        ("expected_parameter_count", 1),
    ],
)
def test_tiny_invariant_mismatch_is_rejected(tiny, field, value):
    changed = deepcopy(tiny)
    changed[field] = value
    with pytest.raises(ConfigValidationError, match=field):
        validate_model_config(changed, "tiny.yaml")


def test_missing_required_model_field_is_rejected(tiny):
    del tiny["hidden_size"]
    with pytest.raises(ConfigValidationError, match="hidden_size"):
        validate_model_config(tiny, "tiny.yaml")


def test_wrong_type_is_rejected(tiny):
    tiny["num_layers"] = "6"
    with pytest.raises(ConfigValidationError, match="num_layers"):
        validate_model_config(tiny, "tiny.yaml")


def test_boolean_is_not_accepted_as_integer(tiny):
    tiny["num_layers"] = True
    with pytest.raises(ConfigValidationError, match="num_layers"):
        validate_model_config(tiny, "tiny.yaml")


def test_unknown_field_is_rejected(tiny):
    tiny["new_option"] = True
    with pytest.raises(ConfigValidationError, match="new_option"):
        validate_model_config(tiny, "tiny.yaml")


def test_disabled_small_config_cannot_execute():
    small = load_yaml(repository_root() / "configs" / "small.yaml")
    with pytest.raises(DisabledConfigError):
        validate_model_config(small, "small.yaml")


def test_incomplete_pretrain_config_fails_complete_validation():
    path = repository_root() / "configs" / "pretrain.yaml"
    run = load_yaml(path)
    validate_run_config(run, path, require_complete=False)
    with pytest.raises(ConfigValidationError, match="실행 전에"):
        validate_run_config(run, path, require_complete=True)


def test_run_rejects_ambiguous_budget_and_external_path():
    path = repository_root() / "configs" / "pretrain.yaml"
    run = load_yaml(path)
    run.update(
        seed=7,
        device="cpu",
        micro_batch=1,
        gradient_accumulation=1,
        learning_rate=0.001,
        warmup=0,
        weight_decay=0,
        max_steps=10,
        token_budget=100,
        checkpoint_interval=5,
        evaluation_interval=5,
        output_directory="artifacts/test",
    )
    with pytest.raises(ConfigValidationError, match="동시에"):
        validate_run_config(run, path)
    run["token_budget"] = None
    run["output_directory"] = "C:\\outside"
    with pytest.raises(ConfigValidationError, match="상대 경로"):
        validate_run_config(run, path)


def test_override_order_and_resolved_config(tmp_path: Path):
    run = load_yaml(repository_root() / "configs" / "pretrain.yaml")
    run.update(
        seed=7,
        device="cpu",
        micro_batch=1,
        gradient_accumulation=1,
        learning_rate=0.001,
        warmup=0,
        weight_decay=0,
        max_steps=10,
        checkpoint_interval=5,
        evaluation_interval=5,
        output_directory="artifacts/test",
    )
    run_path = tmp_path / "run.yaml"
    run_path.write_text(yaml.safe_dump(run), encoding="utf-8")
    resolved = load_resolved_config(
        repository_root() / "configs" / "tiny.yaml",
        run_path,
        overrides={"run.seed": 11},
    )
    assert resolved["run"]["seed"] == 11


def test_unknown_override_is_rejected():
    with pytest.raises(ConfigError, match="존재하지 않는"):
        load_resolved_config(
            repository_root() / "configs" / "tiny.yaml",
            overrides={"model.unknown": 1},
        )


def test_override_parser_and_secret_masking():
    assert parse_overrides(["run.seed=3", "run.device=cuda"]) == {
        "run.seed": 3,
        "run.device": "cuda",
    }
    masked = mask_secrets({"api_key": "value", "token_budget": 123})
    assert masked == {"api_key": "***", "token_budget": 123}
