from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import torch
import yaml
from torch import nn

from src.model import DohaLMOutput, greedy_generate
from src.training import Gate7OverfitConfig, TrainingError
from src.training.gate7_overfit import (
    EXPECTED_CORPUS,
    EXPECTED_MODEL,
    EXPECTED_TOKENIZER,
    EXPECTED_VOCAB,
    _autoregressive_prefix_metrics,
    _classification_counts,
    _packed_teacher_forced_metrics,
    _select_documents,
    _teacher_forced_metrics,
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
        "limits": {"document_count_max": 64, "step_max": 1000},
        "restrictions": restrictions,
    }), encoding="utf-8")


@pytest.mark.parametrize(("field", "value"), (("document_count", 65), ("max_steps", 1001), ("context_length", 512)))
def test_scope_limits_fail_closed(field, value):
    with pytest.raises(TrainingError, match="GATE7_SCOPE_EXCEEDED"):
        config(**{field: value})


def test_learning_rate_is_restricted_to_approved_candidates():
    with pytest.raises(TrainingError, match="GATE7_SCOPE_EXCEEDED"):
        config(learning_rate=2e-4)


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


class AlignedModel(nn.Module):
    def __init__(self, sequence: list[int], *, generated_override: list[int] | None = None):
        super().__init__()
        self.sequence = sequence
        self.generated_override = generated_override
        self.config = type("Config", (), {"vocab_size": 32, "context_length": 256})()

    def forward(self, input_ids, *, attention_mask=None):
        logits = torch.full((*input_ids.shape, self.config.vocab_size), -100.0, device=input_ids.device)
        for position in range(input_ids.shape[1] - 1):
            logits[:, position, input_ids[:, position + 1]] = 100.0
        next_position = input_ids.shape[1]
        next_token = self.sequence[next_position] if next_position < len(self.sequence) else 3
        logits[:, -1, next_token] = 100.0
        return DohaLMOutput(logits=logits)

    def generate(self, input_ids, *, max_new_tokens, eos_token_id=None, attention_mask=None):
        if self.generated_override is not None:
            extra = torch.tensor([self.generated_override[:max_new_tokens]], dtype=torch.long, device=input_ids.device)
            return torch.cat((input_ids, extra), dim=1)
        return greedy_generate(self, input_ids, max_new_tokens=max_new_tokens, eos_token_id=eos_token_id,
                               attention_mask=attention_mask)


def test_teacher_forced_alignment_uses_logits_t_for_target_t_plus_one():
    logits = torch.full((3, 8), -10.0)
    targets = torch.tensor([2, 4, 6])
    logits[torch.arange(3), targets] = 10.0
    result = _classification_counts(logits, targets)
    assert result["token_count"] == result["top1_count"] == result["top5_count"] == 3
    assert result["loss_sum"] < 1e-4


def test_autoregressive_first_token_and_prefix_match_are_aligned():
    sequence = [2, 10, 11, 12, 13, 3]
    result = _autoregressive_prefix_metrics(AlignedModel(sequence), sequence, 2, 3, torch.device("cpu"))
    assert result["prompt_last_logit_index"] == 1
    assert result["target_start_index"] == 2
    assert result["first_target_token_accuracy"] == 1.0
    assert result["token_prefix_match_length"] == 3
    assert result["exact_continuation_match"] is True
    assert result["teacher_forced_top1_accuracy"] == 1.0


def test_prefix_metrics_detect_first_token_match_then_divergence_deterministically():
    sequence = [2, 10, 11, 12, 13, 3]
    model = AlignedModel(sequence, generated_override=[11, 7, 7])
    first = _autoregressive_prefix_metrics(model, sequence, 2, 3, torch.device("cpu"))
    second = _autoregressive_prefix_metrics(model, sequence, 2, 3, torch.device("cpu"))
    assert first == second
    assert first["first_target_token_accuracy"] == 1.0
    assert first["token_prefix_match_length"] == 1
    assert first["exact_continuation_match"] is False
    assert first["adjacent_repeat_count"] == 1


def test_teacher_forced_document_metrics_cover_bos_to_eos_boundaries():
    sequence = [2, 10, 11, 12, 3]
    rows = [{"document_id": "sha256:test", "input_ids": sequence}]
    result = _teacher_forced_metrics(AlignedModel(sequence), rows, config(document_count=1), torch.device("cpu"))
    assert result["target_token_count"] == 4
    assert result["next_token_top1_accuracy"] == 1.0
    assert result["next_token_top5_accuracy"] == 1.0


def test_packed_teacher_forced_metrics_preserve_positions_and_ignore_padding():
    sequence = [2, 10, 11, 3, 0]
    rows = [{
        "input_ids": sequence,
        "labels": [2, 10, 11, 3, -100],
        "attention_mask": [1, 1, 1, 1, 0],
    }]
    result = _packed_teacher_forced_metrics(AlignedModel(sequence), rows, torch.device("cpu"))
    assert result["target_token_count"] == 3
    assert result["next_token_top1_accuracy"] == 1.0
    assert result["next_token_top5_accuracy"] == 1.0
    assert result["evaluation_condition"] == "exact_training_packing_and_absolute_positions"
