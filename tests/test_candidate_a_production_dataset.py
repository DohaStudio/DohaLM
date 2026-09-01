from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path

import src.data.candidate_a_production_dataset as subject
from src.data.checksums import checksum_value
from src.data.current_evidence_snapshot import RightsReadModel, SourceToken
from src.data.rights_metadata_projection import (
    AuthorityRightsMetadata,
    TypedRightsEvidence,
)

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
SOURCE_AUTHORITY = "11111111-1111-4111-8111-111111111111"
RIGHTS_SUBJECT = "22222222-2222-4222-8222-222222222222"
RIGHTS_RECORD = "33333333-3333-4333-8333-333333333333"
PRODUCER = "44444444-4444-4444-8444-444444444444"
REVIEWER = "55555555-5555-4555-8555-555555555555"


@dataclass(frozen=True)
class _Encoding:
    ids: list[int]


class _Tokenizer:
    vocab_size = 16_000
    unk_id = 15_999

    def __init__(self, path: Path) -> None:
        self.path = path

    def encode(self, text: str, *, add_bos: bool, add_eos: bool) -> _Encoding:
        assert add_bos and add_eos
        return _Encoding([1, 2, 3])


def _rights() -> RightsReadModel:
    record_fingerprint = "sha256:" + "a" * 64
    token_fingerprint = "sha256:" + "b" * 64
    metadata = AuthorityRightsMetadata(
        dataset_source_identity="AIHUB-71748",
        subject_kind="source_dataset",
        bound_identity="AIHUB-71748",
        rights_status="approved_limited",
        source_type="external",
        user_created=False,
        generated=False,
        reference=False,
        uploaded=False,
        external=True,
        analysis_allowed=True,
        derivative_generation_allowed=True,
        retention_mode="indefinite_while_current",
        retention_scope="training",
        retention_expires_at=None,
        consent_evidence_references=(),
        jurisdiction="KR",
        reviewer_authority_id=REVIEWER,
        reviewed_at=NOW,
        producer_authority_id=PRODUCER,
        effective_at=NOW,
        current_use_authorized=True,
        current_use_scope="internal_noncommercial_model_training_and_evaluation",
        fresh_acquisition_required=False,
        existing_material_reuse=True,
        historical_acquisition_receipt="not_recovered",
        provider_reacquisition_requirement_found=False,
        typed_evidence_references=(
            TypedRightsEvidence("evidence:provider-policy", "provider_usage_policy"),
        ),
    )
    token = SourceToken(
        SOURCE_AUTHORITY,
        "rights-source-token-v1",
        RIGHTS_SUBJECT,
        RIGHTS_RECORD,
        record_fingerprint,
        1,
        token_fingerprint,
    )
    return RightsReadModel(
        RIGHTS_SUBJECT,
        RIGHTS_RECORD,
        SOURCE_AUTHORITY,
        "rights-source-token-v1",
        True,
        False,
        False,
        False,
        record_fingerprint,
        token,
        metadata,
    )


def _row(data_file: str, index: int) -> dict[str, object]:
    archive = "archive.zip"
    entry = "Training/data.json"
    text = f"record {index}"
    material = f"{archive}\0{entry}\0{index}".encode()
    return {
        "source_archive": archive,
        "source_entry": entry,
        "source_record_index": index,
        "source_id": f"sha256:{hashlib.sha256(material).hexdigest()}",
        "document_id": f"sha256:{hashlib.sha256(text.encode()).hexdigest()}",
        "data_file": data_file,
        "text": text,
    }


def test_group_split_is_stable_and_normalizes_unicode() -> None:
    assert subject.candidate_a_group_key("e\u0301") == subject.candidate_a_group_key(
        "é"
    )
    key = subject.candidate_a_group_key("document-1")
    assert subject.candidate_a_split(key) == subject.candidate_a_split(key)


def test_small_rights_first_build_exercises_real_contract_chain(
    tmp_path: Path, monkeypatch
) -> None:
    names: dict[str, str] = {}
    index = 0
    while set(names) != {"train", "validation", "test"}:
        name = f"group-{index}"
        names.setdefault(
            subject.candidate_a_split(subject.candidate_a_group_key(name)), name
        )
        index += 1
    rows = [_row(names[split], index) for index, split in enumerate(names)]
    allocations = [
        {
            "record_id": row["source_id"],
            "split": subject.candidate_a_split(
                subject.candidate_a_group_key(str(row["data_file"]))
            ),
            "group_id": subject.candidate_a_group_key(str(row["data_file"])),
        }
        for row in rows
    ]
    source_digest = hashlib.sha256()
    for row in rows:
        source_digest.update(str(row["text"]).encode() + b"\n")
    monkeypatch.setattr(subject, "_iter_source_records", lambda *args: iter(rows))
    monkeypatch.setattr(subject, "DohaTokenizer", _Tokenizer)
    monkeypatch.setattr(subject, "EXPECTED_SOURCE_RECORDS", 3)
    monkeypatch.setattr(subject, "EXPECTED_SELECTED_RECORDS", 3)
    monkeypatch.setattr(subject, "EXPECTED_SELECTED_GROUPS", 3)
    monkeypatch.setattr(
        subject,
        "EXPECTED_SPLIT_COUNTS",
        {"train": (1, 1), "validation": (1, 1), "test": (1, 1)},
    )
    monkeypatch.setattr(
        subject,
        "EXPECTED_SOURCE_CORPUS_SHA256",
        f"sha256:{source_digest.hexdigest()}",
    )
    monkeypatch.setattr(
        subject,
        "EXPECTED_ALLOCATION_FINGERPRINT",
        checksum_value(sorted(allocations, key=lambda value: value["record_id"])),
    )
    monkeypatch.setattr(subject, "_validate_eligibility_material", lambda *args: None)
    eligibility = tmp_path / "eligibility.yaml"
    eligibility.write_text("status: approved\n", encoding="utf-8")
    output = tmp_path / "production-v1"
    result = subject.build_candidate_a_production_dataset(
        dataset_root=tmp_path,
        checksum_inventory=tmp_path / "checksums.yaml",
        tokenizer_model=tmp_path / "tokenizer.model",
        eligibility_material=eligibility,
        rights=_rights(),
        output=output,
        reviewed_at=NOW,
    )
    verified = subject.verify_candidate_a_production_dataset(output)
    assert result.selected_records == 3
    assert verified["status"] == "PRODUCTION_DATASET_ARTIFACTS_READY"
    assert verified["cross_split_group_overlap"] == 0
    assert (output / "candidates.jsonl").read_text(encoding="utf-8").count("\n") == 3
    assert (output / "handoffs.jsonl").read_text(encoding="utf-8").count("\n") == 3
