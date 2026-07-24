from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.tokenizer.errors import TokenizerError
from src.tokenizer.manifest import compare_manifests, load_manifest, validate_bundle
from src.tokenizer.trainer import TrainerConfig, train_smoke_tokenizer


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("tokenizer-manifest")
    corpus = Path("tests/fixtures/tokenizer/corpus.txt").resolve()
    output = root / "bundle"
    train_smoke_tokenizer(corpus, output, synthetic_root=corpus.parent, config=TrainerConfig())
    return output


def test_manifest_has_required_lineage_and_no_absolute_path(bundle: Path):
    manifest = load_manifest(bundle / "manifest.json")
    assert manifest["vocab_size"] == manifest["actual_piece_count"] == 256
    assert manifest["sentencepiece_version"] == "0.2.2"
    assert manifest["corpus"]["kind"] == "synthetic_fixture"
    assert manifest["status"] == "smoke_only_not_approved"
    serialized = json.dumps(manifest, ensure_ascii=False)
    assert str(Path.cwd().resolve()) not in serialized
    assert "AIHUB" not in serialized


def test_fingerprint_and_bundle_validation(bundle: Path):
    fingerprint = json.loads((bundle / "fingerprint.json").read_text(encoding="utf-8"))
    assert fingerprint["fingerprint"].startswith("sha256:")
    assert len(fingerprint["fingerprint"]) == 71
    result = validate_bundle(bundle / "tokenizer.model")
    assert result["status"] == "valid_smoke_bundle"
    assert result["artifact_count"] == 5


def test_statistics_report_unknown_and_vocab_usage(bundle: Path):
    statistics = json.loads((bundle / "statistics.json").read_text(encoding="utf-8"))
    assert statistics["record_count"] == 40
    assert statistics["total_tokens"] > 0
    assert statistics["average_tokens_per_record"] > 0
    assert 0 <= statistics["unknown_token_ratio"] <= 1
    assert 0 < statistics["vocab_usage_ratio"] <= 1
    assert statistics["byte_fallback"] is False


def test_bundle_checksum_corruption_is_rejected(bundle: Path, tmp_path: Path):
    corrupt = tmp_path / "corrupt"
    shutil.copytree(bundle, corrupt)
    with (corrupt / "tokenizer.vocab").open("a", encoding="utf-8") as handle:
        handle.write("corrupt\n")
    with pytest.raises(TokenizerError, match="TOKENIZER_CHECKSUM_MISMATCH"):
        validate_bundle(corrupt / "tokenizer.model")


def test_compatibility_states():
    base = {
        "tokenizer_fingerprint": "sha256:a",
        "model_type": "unigram",
        "actual_piece_count": 256,
        "special_tokens": {"<pad>": 0},
        "trainer_config": {"normalization_rule_name": "identity", "byte_fallback": False},
    }
    assert compare_manifests(base, dict(base))["status"] == "compatible"
    warning = {**base, "tokenizer_fingerprint": "sha256:b"}
    assert compare_manifests(base, warning)["status"] == "warning"
    incompatible = {**warning, "actual_piece_count": 128}
    assert compare_manifests(base, incompatible)["status"] == "incompatible"
