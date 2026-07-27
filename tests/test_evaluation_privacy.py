import json
from pathlib import Path

import yaml


def test_public_config_disables_sensitive_output() -> None:
    config = yaml.safe_load(Path("configs/evaluation.example.yaml").read_text(encoding="utf-8"))
    assert config["raw_text_storage"] is False
    assert config["token_id_storage"] is False
    assert config["external_benchmark"] == "disabled"


def test_registry_and_docs_do_not_contain_local_absolute_root() -> None:
    paths = [
        Path("configs/evaluation.example.yaml"),
        Path("configs/evaluation-artifacts.example.yaml"),
        Path("docs/evaluation/candidate-a-final-full-result.md"),
    ]
    assert all("D:\\DohaLM-Datasets" not in path.read_text(encoding="utf-8") for path in paths)


def test_numeric_result_shape_has_no_text_or_token_arrays() -> None:
    value = {"prompt_id_hash": "abc", "length": 4, "token_hash": "def", "decoded_text_stored": False}
    rendered = json.dumps(value)
    assert "prompt_text" not in rendered
    assert "continuation_text" not in rendered
    assert "token_ids" not in rendered
