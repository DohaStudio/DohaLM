from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import yaml

from src.training import Gate7OverfitConfig, TrainingError
from src.training.gate7_overfit import (
    EXPECTED_CORPUS,
    EXPECTED_MODEL,
    EXPECTED_TOKENIZER,
    EXPECTED_VOCAB,
    _select_documents,
    _validate_approval,
    resolve_gate7_paths,
)


def config(**overrides) -> Gate7OverfitConfig:
    values = {
        "local_dataset_config": "configs/local-datasets.yaml",
        "approval_manifest": "docs/data/approval.yaml",
        "package_manifest": "docs/data/package.yaml",
        "checksum_inventory": "docs/data/checksums.yaml",
        "source_corpus": "analysis/source.txt",
        "tokenizer_bundle": "analysis/tokenizer",
        "output_base": "analysis/gate7",
        "device": "cpu",
        "use_amp": False,
    }
    values.update(overrides)
    return Gate7OverfitConfig(**values)


def approval(path: Path, **restriction_overrides) -> None:
    restrictions = {
        "pretraining": "not_approved",
        "gate7_status_change": "not_approved",
        "validation_use": "not_approved",
        "evaluation_benchmark_use": "not_approved",
        "redistribution": "not_approved",
    }
    restrictions.update(restriction_overrides)
    path.write_text(yaml.safe_dump({
        "manifest_status": "approved",
        "approval": {"purpose": "gate7_tiny_overfit_only", "approved_by": "user"},
        "identity": {"corpus_fingerprint": EXPECTED_CORPUS, "tokenizer_fingerprint": EXPECTED_TOKENIZER,
                     "model_sha256": EXPECTED_MODEL, "vocab_sha256": EXPECTED_VOCAB},
        "limits": {"document_count_max": 64, "step_max": 500},
        "restrictions": restrictions,
    }), encoding="utf-8")


@pytest.mark.parametrize(("field", "value"), (("document_count", 65), ("max_steps", 501), ("context_length", 512)))
def test_scope_limits_fail_closed(field, value):
    with pytest.raises(TrainingError, match="GATE7_SCOPE_EXCEEDED"):
        config(**{field: value})


def test_approval_requires_exact_identity_and_broader_training_blocks(tmp_path):
    path = tmp_path / "approval.yaml"
    approval(path)
    assert _validate_approval(config(), path)["manifest_status"] == "approved"
    approval(path, pretraining="approved")
    with pytest.raises(TrainingError, match="GATE7_CONFIG_INVALID"):
        _validate_approval(config(), path)


def test_document_selection_uses_json_record_boundaries_and_is_deterministic(tmp_path, monkeypatch):
    archive = tmp_path / "training.zip"
    contents = [f"record-{index}" for index in range(8)] + ["line-one\nline-two", "record-1", "x" * 5000]
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("source.json", json.dumps({"data_info": [{"contents": value} for value in contents]}))
    monkeypatch.setattr(
        "src.training.gate7_overfit._eligible_archives",
        lambda dataset_root, inventory: [{"path": archive, "relative_path": "Training/01.원천데이터/test.zip"}],
    )
    first, first_counts = _select_documents(tmp_path, tmp_path / "inventory.yaml", config(document_count=4))
    second, second_counts = _select_documents(tmp_path, tmp_path / "inventory.yaml", config(document_count=4))
    assert [row["document_id"] for row in first] == [row["document_id"] for row in second]
    assert len(first) == len({row["document_id"] for row in first}) == 4
    assert first_counts == second_counts
    assert first_counts == {"source_records": 10, "empty": 0, "duplicate": 1, "oversize": 1, "eligible": 9}


def test_paths_are_resolved_below_configured_external_root(tmp_path, monkeypatch):
    external = tmp_path / "external"
    dataset = external / "extracted" / "AIHUB-71748"
    dataset.mkdir(parents=True)
    local = tmp_path / "local.yaml"
    local.write_text(yaml.safe_dump({"datasets": {"external_root": str(external), "entries": {"AIHUB-71748": {"root": "extracted/AIHUB-71748"}}}}), encoding="utf-8")
    monkeypatch.setattr("src.training.gate7_overfit.resolve_repository_path", lambda value: local if value == "configs/local-datasets.yaml" else tmp_path / value)
    paths = resolve_gate7_paths(config(), "run-1")
    assert paths.source_corpus == (external / "analysis/source.txt").resolve()
    assert paths.dataset_root == dataset.resolve()
    assert paths.output_root == (external / "analysis/gate7/run-1").resolve()


def test_run_id_cannot_escape_external_root():
    with pytest.raises(TrainingError, match="GATE7_CONFIG_INVALID"):
        resolve_gate7_paths(config(), "../escape")
