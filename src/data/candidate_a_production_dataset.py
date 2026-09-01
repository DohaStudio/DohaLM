"""ADR-035 RIGHTS-FIRST Candidate A production Dataset rebuild."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from src.tokenizer import DohaTokenizer

from .checksums import canonical_json_bytes, checksum_value, file_checksum
from .common_dataset_contracts import (
    validate_learning_candidate,
    validate_training_eligibility,
)
from .current_evidence_snapshot import RightsReadModel
from .learning_candidate_consumer import (
    ProducerIdentity,
    validate_learning_candidate_for_consumption,
)
from .learning_candidate_dataset_handoff import create_dataset_inclusion_handoff
from .learning_candidate_review import (
    LearningCandidateReviewAuthority,
    ReviewDecision,
    review_learning_candidate,
)
from .pilot_dataset import _iter_source_records, pii_categories
from .product_dataset_composition import (
    ProductDatasetCompositionAuthorityInput,
    ProductDatasetMemberAllocation,
    compose_product_dataset,
)
from .rights_metadata_projection import project_common_rights_metadata
from .sequence_packing import PackingPolicy, pack_sequences
from .splitting import _bucket

DATASET_ID = "AIHUB-71748"
PRODUCTION_NAMESPACE = "production-v1"
SELECTION_POLICY = "aihub-71748-training-selection-v1"
SPLIT_POLICY = "aihub-71748-production-split-v1"
SPLIT_SEED = 17
EXPECTED_SOURCE_RECORDS = 107_226
EXPECTED_SELECTED_RECORDS = 97_747
EXPECTED_SELECTED_GROUPS = 85_992
EXPECTED_SPLIT_COUNTS = {
    "train": (88_071, 77_524),
    "validation": (4_770, 4_193),
    "test": (4_906, 4_275),
}
EXPECTED_SOURCE_CORPUS_SHA256 = (
    "sha256:0c7119106261e9a8487b5e2e1ba76ba220761a2fdaeb14738e968b91fdbeeb00"
)
EXPECTED_SOURCE_CORPUS_FINGERPRINT = (
    "sha256:2812606509281c9246c56c5bad2efbcf53897a105b75e1843d61b2101891f28c"
)
EXPECTED_ALLOCATION_FINGERPRINT = (
    "sha256:0eee73ff569f1608183805deca1180bb3d8aa909c5fa0dd93d93904691c8308c"
)
USAGE_PURPOSE = "internal_noncommercial_full_pretraining"
CREATED_BY = "dohalm-dataset-governance-candidate-a-production-v1"
CANDIDATE_PRODUCER = ProducerIdentity("dohalm-dataset-ingestion", "1.0.0")
ELIGIBILITY_PRODUCER = ProducerIdentity("dohalm-candidate-eligibility", "1.0.0")
COMPOSITION_PRODUCER = ProducerIdentity("dohalm-product-dataset-composition", "1.0.0")
RIGHTS_PRODUCER = ProducerIdentity("DohaRights", "0.2.0")
REVIEWER_ID = "dohalm-dataset-governance-candidate-review-v1"
SCHEMA_MANIFEST_ID = (
    "schema-manifest:dohastudio-common-ai-contracts:0.1.0:"
    "dd75fc88c16e9ae9a04acfafb72756a905f6365b"
)


class CandidateAProductionDatasetError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"{code}:candidate_a_production_dataset")


@dataclass(frozen=True, slots=True)
class CandidateAProductionBuildResult:
    output: Path
    dataset_fingerprint: str
    composition_id: str
    source_fingerprint: str
    content_fingerprint: str
    selected_records: int
    selected_groups: int
    split_counts: dict[str, int]
    allocation_fingerprint: str
    artifact_checksums_fingerprint: str


class CandidateACurrentEvidenceAuthority(LearningCandidateReviewAuthority):
    """Deterministic current resolver over one owner Rights record and approved membership."""

    def __init__(
        self,
        *,
        rights_metadata: dict[str, object],
        selected_source_digests: set[str],
        reviewed_at: datetime,
        expires_at: datetime,
        eligibility_evidence_id: str,
    ) -> None:
        self._rights = rights_metadata
        self._rights_id = str(rights_metadata["rights_metadata_id"])
        self._selected = selected_source_digests
        self._reviewed_at = reviewed_at
        self._expires_at = expires_at
        self._evidence_id = eligibility_evidence_id

    def resolve_rights_metadata(
        self, rights_metadata_id: str, *, checked_at: datetime
    ) -> object | None:
        return self._rights if rights_metadata_id == self._rights_id else None

    def resolve_training_eligibility(
        self, training_eligibility_id: str, *, checked_at: datetime
    ) -> object | None:
        prefix = "eligibility:aihub-71748-production-v1:"
        if not training_eligibility_id.startswith(prefix):
            return None
        digest = training_eligibility_id.removeprefix(prefix)
        if digest not in self._selected:
            return None
        return _eligibility_payload(
            digest,
            rights_metadata_id=self._rights_id,
            reviewed_at=self._reviewed_at,
            expires_at=self._expires_at,
            eligibility_evidence_id=self._evidence_id,
        )


def candidate_a_group_key(data_file: str) -> str:
    if not isinstance(data_file, str) or not data_file.strip():
        raise CandidateAProductionDatasetError("DATA_FILE_GROUP_MISSING")
    logical = unicodedata.normalize("NFC", data_file)
    return f"group:sha256:{hashlib.sha256(logical.encode('utf-8')).hexdigest()}"


def candidate_a_split(group_key: str) -> str:
    value = _bucket(SPLIT_SEED, group_key)
    return "train" if value < 0.90 else "validation" if value < 0.95 else "test"


def candidate_a_id(source_id: str) -> str:
    digest = _sha_digest(source_id, "SOURCE_ID_INVALID")
    return f"candidate:aihub-71748-production-v1:{digest}"


def build_candidate_a_production_dataset(
    *,
    dataset_root: Path,
    checksum_inventory: Path,
    tokenizer_model: Path,
    eligibility_material: Path,
    rights: RightsReadModel,
    output: Path,
    reviewed_at: datetime,
) -> CandidateAProductionBuildResult:
    """Build immutable production artifacts without Dataset publication or Training."""

    reviewed_at = _aware(reviewed_at, "REVIEW_TIME_INVALID")
    output = output.resolve()
    if output.exists():
        raise CandidateAProductionDatasetError("PRODUCTION_OUTPUT_EXISTS")
    rights_metadata = project_common_rights_metadata(rights)
    _require_rights_source(rights)
    eligibility_fingerprint = file_checksum(eligibility_material)
    eligibility_evidence_id = (
        f"eligibility-evidence:aihub-71748-production-v1:{eligibility_fingerprint[7:]}"
    )
    _validate_eligibility_material(eligibility_material, eligibility_fingerprint)
    expires_at = reviewed_at + timedelta(hours=24)
    tokenizer = DohaTokenizer(tokenizer_model)
    if tokenizer.vocab_size != 16_000:
        raise CandidateAProductionDatasetError("TOKENIZER_MISMATCH")

    staging = output.with_name(f".{output.name}.staging-{os.getpid()}")
    if staging.exists():
        raise CandidateAProductionDatasetError("PRODUCTION_STAGING_EXISTS")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    corpus_handles: dict[str, Any] = {}
    evidence_handles: dict[str, Any] = {}
    source_digest = hashlib.sha256()
    selected_digests: set[str] = set()
    group_owners: dict[str, str] = {}
    split_records = Counter()
    split_groups: dict[str, set[str]] = {name: set() for name in EXPECTED_SPLIT_COUNTS}
    exclusion_counts = Counter()
    handoffs = []
    allocations = []
    review_aggregate = []
    allocation_evidence = []
    try:
        for split in EXPECTED_SPLIT_COUNTS:
            corpus_handles[split] = (staging / f"{split}-corpus.jsonl").open(
                "x", encoding="utf-8", newline="\n"
            )
        for name in ("candidates", "eligibilities", "reviews", "handoffs", "members"):
            evidence_handles[name] = (staging / f"{name}.jsonl").open(
                "x", encoding="utf-8", newline="\n"
            )
        source_count = 0
        selected_count = 0
        for row in _iter_source_records(dataset_root, checksum_inventory):
            source_count += 1
            encoded = row["text"].encode("utf-8")
            source_digest.update(encoded + b"\n")
            _validate_source_identity(row)
            if pii_categories(row["text"]):
                exclusion_counts["pii"] += 1
                continue
            group_key = candidate_a_group_key(row["data_file"])
            split = candidate_a_split(group_key)
            previous = group_owners.setdefault(group_key, split)
            if previous != split:
                raise CandidateAProductionDatasetError("CROSS_SPLIT_GROUP")
            digest = _sha_digest(row["source_id"], "SOURCE_ID_INVALID")
            if digest in selected_digests:
                raise CandidateAProductionDatasetError("DUPLICATE_SOURCE_ID")
            selected_digests.add(digest)
            selected_count += 1
            split_records[split] += 1
            split_groups[split].add(group_key)
        _require_source_counts(
            source_count, source_digest, selected_count, split_records, split_groups
        )

        authority = CandidateACurrentEvidenceAuthority(
            rights_metadata=rights_metadata,
            selected_source_digests=selected_digests,
            reviewed_at=reviewed_at,
            expires_at=expires_at,
            eligibility_evidence_id=eligibility_evidence_id,
        )
        selected_seen: set[str] = set()
        for source_row in _iter_source_records(dataset_root, checksum_inventory):
            _validate_source_identity(source_row)
            if pii_categories(source_row["text"]):
                continue
            group_key = candidate_a_group_key(source_row["data_file"])
            split = candidate_a_split(group_key)
            digest = _sha_digest(source_row["source_id"], "SOURCE_ID_INVALID")
            if digest not in selected_digests or digest in selected_seen:
                raise CandidateAProductionDatasetError("SOURCE_REPLAY_MISMATCH")
            selected_seen.add(digest)
            row = {
                **source_row,
                "source_digest": digest,
                "group_key": group_key,
                "split": split,
            }
            candidate = _candidate_payload(row, rights_metadata, reviewed_at)
            eligibility = _eligibility_payload(
                digest,
                rights_metadata_id=str(rights_metadata["rights_metadata_id"]),
                reviewed_at=reviewed_at,
                expires_at=expires_at,
                eligibility_evidence_id=eligibility_evidence_id,
            )
            validated = validate_learning_candidate_for_consumption(
                candidate,
                rights_metadata=rights_metadata,
                training_eligibility=eligibility,
                evaluated_at=reviewed_at,
                usage_purpose=USAGE_PURPOSE,
            )
            review_reference = f"review:aihub-71748-production-v1:{digest}"
            review = review_learning_candidate(
                validated,
                reviewer_id=REVIEWER_ID,
                reviewed_at=reviewed_at,
                requested_decision=ReviewDecision.ACCEPTED,
                review_evidence_reference=review_reference,
                authority=authority,
            )
            handoff = create_dataset_inclusion_handoff(
                review,
                handoff_created_at=reviewed_at,
                authority=authority,
            )
            allocation = ProductDatasetMemberAllocation(
                handoff.handoff_id, row["split"], row["group_key"]
            )
            handoffs.append(handoff)
            allocations.append(allocation)
            review_aggregate.append(
                {
                    "candidate_id": validated.candidate_id,
                    "content_fingerprint": validated.content_fingerprint,
                    "review_evidence_reference": review_reference,
                }
            )
            allocation_evidence.append(
                {
                    "record_id": row["source_id"],
                    "split": row["split"],
                    "group_id": row["group_key"],
                }
            )
            corpus_handles[row["split"]].write(
                json.dumps(
                    {
                        "candidate_id": validated.candidate_id,
                        "source_id": row["source_id"],
                        "text": row["text"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            _write_jsonl(evidence_handles["candidates"], candidate)
            _write_jsonl(evidence_handles["eligibilities"], eligibility)
            _write_jsonl(evidence_handles["reviews"], review)
            _write_jsonl(evidence_handles["handoffs"], handoff)
            _write_jsonl(
                evidence_handles["members"],
                {
                    "candidate_id": validated.candidate_id,
                    "content_fingerprint": validated.content_fingerprint,
                    "group_key": row["group_key"],
                    "handoff_id": handoff.handoff_id,
                    "source_id": row["source_id"],
                    "split": row["split"],
                },
            )
        if selected_seen != selected_digests:
            raise CandidateAProductionDatasetError("SOURCE_REPLAY_MISMATCH")
    except Exception:
        _close(corpus_handles, evidence_handles)
        if staging.exists():
            shutil.rmtree(staging)
        raise
    _close(corpus_handles, evidence_handles)

    allocation_fingerprint = checksum_value(
        sorted(allocation_evidence, key=lambda x: x["record_id"])
    )
    if allocation_fingerprint != EXPECTED_ALLOCATION_FINGERPRINT:
        shutil.rmtree(staging)
        raise CandidateAProductionDatasetError("ALLOCATION_FINGERPRINT_MISMATCH")
    approval_fingerprint = checksum_value(
        sorted(review_aggregate, key=lambda value: value["candidate_id"])
    )
    approval_evidence_id = (
        f"approval-evidence:aihub-71748-production-v1:{approval_fingerprint[7:]}"
    )
    precomposition = {
        "dataset_id": DATASET_ID,
        "namespace": PRODUCTION_NAMESPACE,
        "member_manifest_fingerprint": file_checksum(staging / "members.jsonl"),
        "selection_policy": SELECTION_POLICY,
        "split_policy": SPLIT_POLICY,
        "split_seed": SPLIT_SEED,
        "split_counts": dict(sorted(split_records.items())),
        "rights_metadata_id": rights_metadata["rights_metadata_id"],
        "rights_source_token_fingerprint": rights.token.token_fingerprint,
    }
    dataset_manifest_fingerprint = checksum_value(precomposition)
    dataset_manifest_id = (
        f"dataset-manifest:aihub-71748-production-v1:{dataset_manifest_fingerprint[7:]}"
    )
    authority_input = ProductDatasetCompositionAuthorityInput(
        object_id="dataset:aihub-71748-production-v1",
        dataset_id=DATASET_ID,
        dataset_version="1.0.0",
        created_at=reviewed_at,
        created_by=CREATED_BY,
        producer=COMPOSITION_PRODUCER,
        workspace_id=None,
        schema_manifest_id=SCHEMA_MANIFEST_ID,
        dataset_manifest_id=dataset_manifest_id,
        dataset_eligibility_evidence_id=eligibility_evidence_id,
        approval_evidence_ids=(approval_evidence_id,),
        allocations=tuple(allocations),
    )
    composition = compose_product_dataset(
        handoffs,
        authority_input=authority_input,
        current_authority=authority,
        composed_at=reviewed_at,
    )
    _write_json(staging / "rights-metadata.json", rights_metadata)
    _write_json(staging / "composition.json", composition)
    packing = _build_packed_artifacts(staging, tokenizer)
    split_manifest = {
        "schema_version": "1.0.0",
        "policy_version": SPLIT_POLICY,
        "seed": SPLIT_SEED,
        "ratios": {"train": 0.90, "validation": 0.05, "test": 0.05},
        "allocation_fingerprint": allocation_fingerprint,
        "cross_split_group_overlap": 0,
        "statistics": {
            name: {
                "records": split_records[name],
                "groups": len(split_groups[name]),
            }
            for name in EXPECTED_SPLIT_COUNTS
        },
    }
    _write_json(staging / "split-manifest.json", split_manifest)
    source_manifest = {
        "schema_version": "1.0.0",
        "dataset_id": DATASET_ID,
        "selection_policy": SELECTION_POLICY,
        "source_record_count": EXPECTED_SOURCE_RECORDS,
        "source_corpus_sha256": EXPECTED_SOURCE_CORPUS_SHA256,
        "source_corpus_fingerprint": EXPECTED_SOURCE_CORPUS_FINGERPRINT,
        "selected_record_count": EXPECTED_SELECTED_RECORDS,
        "excluded_record_count": exclusion_counts["pii"],
        "synthetic_provenance_count": 0,
    }
    _write_json(staging / "source-lineage-manifest.json", source_manifest)
    dataset_identity = {
        **precomposition,
        "composition_id": composition.composition_id,
        "composition_source_fingerprint": composition.source_fingerprint,
        "composition_content_fingerprint": composition.content_fingerprint,
        "split_manifest_fingerprint": file_checksum(staging / "split-manifest.json"),
        "train_artifact": file_checksum(staging / "train.jsonl"),
        "validation_artifact": file_checksum(staging / "validation.jsonl"),
        "test_artifact": file_checksum(staging / "test.jsonl"),
        "tokenizer_fingerprint": (
            "sha256:9ce19a118a893fd69bad3124f94cea78f804d450a2ff6a9c4149b3064312f0ff"
        ),
        "tokenization_fingerprint": packing["tokenization_fingerprint"],
        "packing_fingerprint": packing["packing_fingerprint"],
    }
    dataset_fingerprint = checksum_value(dataset_identity)
    dataset_manifest = {
        "schema_version": "1.0.0",
        "status": "ready_for_dataset_version_proposal",
        "dataset_id": DATASET_ID,
        "namespace": PRODUCTION_NAMESPACE,
        "dataset_manifest_id": dataset_manifest_id,
        "dataset_fingerprint": dataset_fingerprint,
        "rights_metadata_id": rights_metadata["rights_metadata_id"],
        "rights_source_token_fingerprint": rights.token.token_fingerprint,
        "internal_training_allowed": True,
        "commercial_use_allowed": False,
        "redistribution_allowed": False,
        "external_model_publication_allowed": False,
        "actual_dataset_publication": 0,
        "actual_training_workload": 0,
        "identity": dataset_identity,
    }
    _write_json(staging / "dataset-manifest.json", dataset_manifest)
    artifact_checksums = {
        path.name: file_checksum(path)
        for path in sorted(staging.iterdir())
        if path.is_file()
    }
    checksums_fingerprint = checksum_value(artifact_checksums)
    _write_json(
        staging / "artifact-checksums.json",
        {"files": artifact_checksums, "fingerprint": checksums_fingerprint},
    )
    _write_json(
        staging / "COMPLETE.json",
        {
            "status": "PRODUCTION_DATASET_ARTIFACTS_READY",
            "dataset_fingerprint": dataset_fingerprint,
            "artifact_checksums_fingerprint": checksums_fingerprint,
            "actual_dataset_publication": 0,
            "actual_training_workload": 0,
        },
    )
    os.replace(staging, output)
    return CandidateAProductionBuildResult(
        output,
        dataset_fingerprint,
        composition.composition_id,
        composition.source_fingerprint,
        composition.content_fingerprint,
        EXPECTED_SELECTED_RECORDS,
        EXPECTED_SELECTED_GROUPS,
        dict(split_records),
        allocation_fingerprint,
        checksums_fingerprint,
    )


def verify_candidate_a_production_dataset(output: Path) -> dict[str, object]:
    output = output.resolve()
    complete = _read_json(output / "COMPLETE.json")
    checksums = _read_json(output / "artifact-checksums.json")
    files = checksums.get("files")
    if (
        complete.get("status") != "PRODUCTION_DATASET_ARTIFACTS_READY"
        or not isinstance(files, dict)
        or any(file_checksum(output / name) != digest for name, digest in files.items())
        or checksum_value(files) != checksums.get("fingerprint")
    ):
        raise CandidateAProductionDatasetError("PRODUCTION_ARTIFACT_INVALID")
    manifest = _read_json(output / "dataset-manifest.json")
    split = _read_json(output / "split-manifest.json")
    if (
        manifest.get("actual_dataset_publication") != 0
        or manifest.get("actual_training_workload") != 0
        or split.get("allocation_fingerprint") != EXPECTED_ALLOCATION_FINGERPRINT
        or {
            name: (
                split["statistics"][name]["records"],
                split["statistics"][name]["groups"],
            )
            for name in EXPECTED_SPLIT_COUNTS
        }
        != EXPECTED_SPLIT_COUNTS
    ):
        raise CandidateAProductionDatasetError("PRODUCTION_ARTIFACT_IDENTITY_MISMATCH")
    return {
        "status": complete["status"],
        "dataset_fingerprint": manifest["dataset_fingerprint"],
        "artifact_checksums_fingerprint": checksums["fingerprint"],
        "selected_records": EXPECTED_SELECTED_RECORDS,
        "selected_groups": EXPECTED_SELECTED_GROUPS,
        "cross_split_group_overlap": 0,
    }


def _candidate_payload(
    row: dict[str, Any], rights_metadata: dict[str, object], created_at: datetime
) -> dict[str, object]:
    digest = row["source_digest"]
    candidate_id = candidate_a_id(row["source_id"])
    payload: dict[str, object] = {
        "schema_name": "learning_candidate",
        "schema_version": "1.0.0",
        "object_id": candidate_id,
        "created_at": _utc(created_at),
        "created_by": CREATED_BY,
        "producer": asdict(CANDIDATE_PRODUCER),
        "candidate_id": candidate_id,
        "source_type": "human_authored",
        "task": "base_pretraining",
        "status": "approved",
        "input_refs": [
            {
                "object_id": f"source:{digest}",
                "schema_name": "source_record",
                "schema_version": "1.0.0",
                "content_fingerprint": row["document_id"],
            }
        ],
        "output_refs": [
            {
                "object_id": f"content:{row['document_id'][7:]}",
                "schema_name": "normalized_text",
                "schema_version": "1.0.0",
                "content_fingerprint": row["document_id"],
            }
        ],
        "rights_metadata_id": rights_metadata["rights_metadata_id"],
        "review_evidence_ids": [
            "policy:ADR-035",
            f"validation:aihub-71748-production-v1:{digest}",
        ],
        "content_fingerprint": row["document_id"],
        "parent_candidate_ids": [],
        "extensions": {
            "dohalm.candidate_a": {
                "selection_policy": SELECTION_POLICY,
                "split_policy": SPLIT_POLICY,
                "source_archive": row["source_archive"],
                "source_entry": row["source_entry"],
                "source_record_index": row["source_record_index"],
                "source_id": row["source_id"],
                "group_key": row["group_key"],
                "split": row["split"],
            }
        },
    }
    validate_learning_candidate(payload)
    return payload


def _eligibility_payload(
    digest: str,
    *,
    rights_metadata_id: str,
    reviewed_at: datetime,
    expires_at: datetime,
    eligibility_evidence_id: str,
) -> dict[str, object]:
    candidate_id = f"candidate:aihub-71748-production-v1:{digest}"
    eligibility_id = f"eligibility:aihub-71748-production-v1:{digest}"
    payload: dict[str, object] = {
        "schema_name": "training_eligibility",
        "schema_version": "1.0.0",
        "object_id": eligibility_id,
        "created_at": _utc(reviewed_at),
        "created_by": CREATED_BY,
        "producer": asdict(ELIGIBILITY_PRODUCER),
        "training_eligibility_id": eligibility_id,
        "candidate_id": candidate_id,
        "candidate_status": "approved",
        "rights_metadata_id": rights_metadata_id,
        "policy_version": "1.0.0",
        "usage_purpose": USAGE_PURPOSE,
        "checks": {
            name: "pass"
            for name in (
                "review",
                "rights",
                "provenance",
                "consent",
                "retention",
                "purpose_scope",
                "quality",
                "pii",
                "lineage",
                "reference_source_separation",
            )
        },
        "approved": True,
        "training_allowed": True,
        "decision": "eligible",
        "reason_codes": [],
        "reviewed_by": REVIEWER_ID,
        "reviewed_at": _utc(reviewed_at),
        "expires_at": _utc(expires_at),
        "extensions": {
            "dohalm.candidate_a": {
                "dataset_eligibility_evidence_id": eligibility_evidence_id,
                "validity_policy": "candidate-a-current-review-24h-v1",
            }
        },
    }
    validate_training_eligibility(payload)
    return payload


def _build_packed_artifacts(staging: Path, tokenizer: DohaTokenizer) -> dict[str, str]:
    policy = PackingPolicy(
        context_length=256, mode="continuous", append_eos=False, remainder="pad"
    )
    tokenization: dict[str, dict[str, object]] = {}
    packing: dict[str, dict[str, int]] = {}
    for split in EXPECTED_SPLIT_COUNTS:
        source = staging / f"{split}-corpus.jsonl"
        target = staging / f"{split}.jsonl"
        token_count = sequence_count = padding_count = 0

        def records() -> Iterator[list[int]]:
            nonlocal token_count
            with source.open("r", encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    ids = tokenizer.encode(row["text"], add_bos=True, add_eos=True).ids
                    if not ids or tokenizer.unk_id in ids:
                        raise CandidateAProductionDatasetError("TOKENIZATION_INVALID")
                    token_count += len(ids)
                    yield ids

        with target.open("x", encoding="utf-8", newline="\n") as handle:
            for packed in pack_sequences(records(), policy):
                handle.write(
                    json.dumps(packed, sort_keys=True, separators=(",", ":")) + "\n"
                )
                sequence_count += 1
                padding_count += packed["attention_mask"].count(0)
        tokenization[split] = {
            "records": EXPECTED_SPLIT_COUNTS[split][0],
            "tokens": token_count,
            "artifact": file_checksum(target),
        }
        packing[split] = {"sequences": sequence_count, "padding_tokens": padding_count}
    tokenization_manifest = {
        "schema_version": "1.0.0",
        "tokenizer_fingerprint": (
            "sha256:9ce19a118a893fd69bad3124f94cea78f804d450a2ff6a9c4149b3064312f0ff"
        ),
        "splits": tokenization,
    }
    packing_manifest = {
        "schema_version": "1.0.0",
        "policy": policy.to_dict(),
        "splits": packing,
    }
    _write_json(staging / "tokenization-manifest.json", tokenization_manifest)
    _write_json(staging / "packing-manifest.json", packing_manifest)
    return {
        "tokenization_fingerprint": checksum_value(tokenization_manifest),
        "packing_fingerprint": checksum_value(packing_manifest),
    }


def _validate_source_identity(row: dict[str, Any]) -> None:
    material = (
        f"{row['source_archive']}\0{row['source_entry']}\0{row['source_record_index']}"
    ).encode("utf-8")
    expected = f"sha256:{hashlib.sha256(material).hexdigest()}"
    if row["source_id"] != expected or row["document_id"] != (
        f"sha256:{hashlib.sha256(row['text'].encode('utf-8')).hexdigest()}"
    ):
        raise CandidateAProductionDatasetError("SOURCE_IDENTITY_MISMATCH")


def _require_source_counts(
    source_count: int,
    source_digest: Any,
    selected_count: int,
    split_records: Counter[str],
    split_groups: dict[str, set[str]],
) -> None:
    actual_source = f"sha256:{source_digest.hexdigest()}"
    actual = {
        name: (split_records[name], len(split_groups[name]))
        for name in EXPECTED_SPLIT_COUNTS
    }
    if (
        source_count != EXPECTED_SOURCE_RECORDS
        or actual_source != EXPECTED_SOURCE_CORPUS_SHA256
        or selected_count != EXPECTED_SELECTED_RECORDS
        or len(set().union(*split_groups.values())) != EXPECTED_SELECTED_GROUPS
        or actual != EXPECTED_SPLIT_COUNTS
    ):
        raise CandidateAProductionDatasetError("SOURCE_SELECTION_MISMATCH")


def _require_rights_source(rights: RightsReadModel) -> None:
    facts = rights.metadata
    if (
        facts is None
        or facts.dataset_source_identity != DATASET_ID
        or facts.subject_kind != "source_dataset"
        or facts.bound_identity != DATASET_ID
        or facts.fresh_acquisition_required
        or not facts.existing_material_reuse
        or facts.historical_acquisition_receipt != "not_recovered"
        or rights.commercial_use
        or rights.redistribution
        or rights.model_publication
    ):
        raise CandidateAProductionDatasetError("RIGHTS_SOURCE_SCOPE_MISMATCH")


def _validate_eligibility_material(path: Path, fingerprint: str) -> None:
    import yaml

    material = yaml.safe_load(path.read_text(encoding="utf-8"))
    if (
        fingerprint
        != "sha256:e9087addc427fd508d66740296c6536a76bc9431a427f8a02828d1b117ff20b0"
        or material.get("status") != "approved"
        or material.get("dataset_id") != DATASET_ID
        or material.get("internal_training_allowed") is not True
        or material.get("commercial_usage_allowed") is not False
        or material.get("dataset_redistribution_allowed") is not False
        or material.get("model_publication_allowed") is not False
    ):
        raise CandidateAProductionDatasetError("ELIGIBILITY_MATERIAL_MISMATCH")


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(_jsonable(value)))


def _write_jsonl(handle: Any, value: object) -> None:
    handle.write(
        json.dumps(
            _jsonable(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def _jsonable(value: object) -> Any:
    if is_dataclass(value):
        return {
            field.name: _jsonable(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _close(*groups: dict[str, Any]) -> None:
    for group in groups:
        for handle in group.values():
            handle.close()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise CandidateAProductionDatasetError("PRODUCTION_ARTIFACT_INVALID") from None
    if not isinstance(value, dict):
        raise CandidateAProductionDatasetError("PRODUCTION_ARTIFACT_INVALID")
    return value


def _sha_digest(value: object, code: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise CandidateAProductionDatasetError(code)
    return value[7:]


def _aware(value: datetime, code: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise CandidateAProductionDatasetError(code)
    return value.astimezone(timezone.utc)


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "CandidateACurrentEvidenceAuthority",
    "CandidateAProductionBuildResult",
    "CandidateAProductionDatasetError",
    "build_candidate_a_production_dataset",
    "candidate_a_group_key",
    "candidate_a_id",
    "candidate_a_split",
    "verify_candidate_a_production_dataset",
]
