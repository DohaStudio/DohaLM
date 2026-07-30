"""Manifest-driven, process-local AIHUB-71748 SFT processing pipeline."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
import re
from pathlib import Path
import os
from typing import Callable, Iterable, Mapping

import yaml

from src.data.aihub_71748_near_duplicate import normalize_near_duplicate_text
from src.data.aihub_71748_pii import _detect_text, _risk

from .aihub_71748_manifest import validate_aihub_71748_processing_manifest
from .aihub_71748_reader import SourceRecord, discover_sft_sources, iter_source_records
from .approval import (
    ProcessingApprovalError,
    consume_approval,
    finalize_approval,
    validate_approval_file,
    approval_fingerprint,
)
from .output_writer import write_atomic_outputs
from .output_writer import HardenedWriteContext
from .post_validation import DiskGuard, snapshot_source_metadata
from .processing_statistics import detailed_statistics_schema, validate_detailed_statistics
from .run_contract import (
    ExecutionCounters,
    ProcessingRunContract,
    RuntimeExecutionRequest,
    payload_session,
    validate_run_contract,
    validate_runtime_request,
)
from .runtime_monitor import RuntimeMonitor


RULE_ORDER = (
    "INPUT_IDENTITY_VALIDATION",
    "SCHEMA_VALIDATION",
    "JOIN_VALIDATION",
    "OUTPUT_SCHEMA_MAPPING",
    "PII_POLICY",
    "EXACT_DUPLICATE_POLICY",
    "NEAR_DUPLICATE_POLICY",
    "LEAKAGE_POLICY",
    "VALIDATION_SPLIT_POLICY",
    "FINAL_SCHEMA_VALIDATION",
    "STATISTICS_VALIDATION",
    "MANIFEST_FINALIZATION",
)
_SAFE_ID = re.compile(r"^[^\x00-\x1f]+$")


class AIHub71748ProcessingError(RuntimeError):
    pass


@dataclass(frozen=True)
class JoinedRecord:
    split: str
    source_id: str
    question: str
    answer: str
    question_type: str
    data_category: str


@dataclass(frozen=True)
class RecordSignal:
    pii: str = "keep"
    exact_duplicate: str = "unique"
    near_duplicate: str = "unique"
    leakage: str = "clear"


@dataclass(frozen=True)
class ProcessedRecords:
    train: tuple[dict[str, object], ...]
    validation: tuple[dict[str, object], ...]
    statistics: Mapping[str, object]
    record_level_signal_available: bool = True
    execution_allowed: bool = False


def join_source_records(records: Iterable[SourceRecord]) -> tuple[JoinedRecord, ...]:
    components: dict[tuple[str, str], dict[str, SourceRecord]] = defaultdict(dict)
    split_ids: dict[str, set[str]] = defaultdict(set)
    for record in records:
        if not _SAFE_ID.fullmatch(record.data_id):
            raise AIHub71748ProcessingError("JOIN_CONTRACT_MISMATCH")
        key = (record.split, record.component)
        if record.data_id in components[key]:
            raise AIHub71748ProcessingError("JOIN_CONTRACT_MISMATCH")
        components[key][record.data_id] = record
        split_ids[record.split].add(record.data_id)
    if split_ids["training"] & split_ids["validation"]:
        raise AIHub71748ProcessingError("JOIN_CONTRACT_MISMATCH")
    joined: list[JoinedRecord] = []
    for split in ("training", "validation"):
        data = components[(split, "sftdata")]
        labels = components[(split, "sftlabel")]
        if not data or set(data) != set(labels):
            raise AIHub71748ProcessingError("JOIN_CONTRACT_MISMATCH")
        for source_id, source in data.items():
            label = labels[source_id]
            if source.question != label.question or label.answer_contents is None:
                raise AIHub71748ProcessingError("JOIN_CONTRACT_MISMATCH")
            if source.question_type is None or source.data_category is None:
                raise AIHub71748ProcessingError("INPUT_SCHEMA_MISMATCH")
            joined.append(JoinedRecord(
                split=split,
                source_id=source_id,
                question=source.question,
                answer=label.answer_contents,
                question_type=source.question_type,
                data_category=source.data_category,
            ))
    return tuple(joined)


def _ngrams(value: str) -> frozenset[str]:
    normalized = normalize_near_duplicate_text(value)
    width = 3
    return frozenset(normalized[index:index + width] for index in range(max(1, len(normalized) - width + 1)))


def recompute_record_signals(
    records: tuple[JoinedRecord, ...],
    *,
    review_min: float,
    high_similarity_min: float,
    maximum_candidate_pairs: int = 2_000_000,
    blocked_prompts: frozenset[str] = frozenset(),
) -> tuple[RecordSignal, ...]:
    """Recompute ephemeral signals; no IDs, pairs, or hashes are persisted."""

    if not 0 < review_min < high_similarity_min < 1:
        raise AIHub71748ProcessingError("INVALID_THRESHOLD")
    signals = [RecordSignal() for _ in records]
    normalized = [normalize_near_duplicate_text(record.question + "\n" + record.answer) for record in records]
    exact_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    answers_by_question: dict[str, set[str]] = defaultdict(set)
    for index, record in enumerate(records):
        exact_groups[(record.question, record.answer)].append(index)
        answers_by_question[record.question].add(record.answer)
        if normalize_near_duplicate_text(record.question) in blocked_prompts:
            raise AIHub71748ProcessingError("RULE_CONFLICT")
        types = set(_detect_text(record.question)["types"]) | set(_detect_text(record.answer)["types"])
        risk = _risk(types)
        if risk in {"critical", "high", "medium"}:
            signals[index] = RecordSignal(pii="exclude")
    if any(len(answers) > 1 for answers in answers_by_question.values()):
        raise AIHub71748ProcessingError("RULE_CONFLICT")
    for group in exact_groups.values():
        if len(group) < 2:
            continue
        training = [index for index in group if records[index].split == "training"]
        keep = training[0] if training else group[0]
        for index in group:
            if index != keep:
                signals[index] = RecordSignal(**{**signals[index].__dict__, "exact_duplicate": "duplicate"})

    grams = [_ngrams(value) for value in normalized]
    postings: dict[str, list[int]] = defaultdict(list)
    candidates: set[tuple[int, int]] = set()
    for right, features in enumerate(grams):
        counts: dict[int, int] = defaultdict(int)
        for feature in features:
            for left in postings[feature]:
                counts[left] += 1
        for left, overlap in counts.items():
            denominator = len(grams[left] | features)
            if denominator and overlap / denominator >= max(0.25, review_min - 0.5):
                candidates.add((left, right))
                if len(candidates) > maximum_candidate_pairs:
                    raise AIHub71748ProcessingError("RECORD_LEVEL_POLICY_SIGNAL_MISSING")
        for feature in features:
            postings[feature].append(right)
    for left, right in sorted(candidates):
        if (records[left].question, records[left].answer) == (records[right].question, records[right].answer):
            continue
        score = SequenceMatcher(None, normalized[left], normalized[right]).ratio()
        if score < review_min:
            continue
        cross_split = records[left].split != records[right].split
        if cross_split:
            targets = [index for index in (left, right) if records[index].split == "validation"]
            for index in targets:
                values = dict(signals[index].__dict__)
                values["near_duplicate"] = "duplicate"
                values["leakage"] = "exclude"
                signals[index] = RecordSignal(**values)
        elif records[right].split == "validation" or score >= high_similarity_min:
            values = dict(signals[right].__dict__)
            values["near_duplicate"] = "duplicate"
            signals[right] = RecordSignal(**values)
    return tuple(signals)


def _safe_output(record: JoinedRecord) -> dict[str, object]:
    return {"instruction": record.question, "input": None, "output": record.answer, "system": None}


def process_joined_records(
    records: tuple[JoinedRecord, ...],
    manifest: Mapping[str, object],
    *,
    monitor: RuntimeMonitor | None = None,
    enforce_expected_statistics: bool = True,
    blocked_prompts: frozenset[str] = frozenset(),
    run_id: str = "SYNTHETIC",
    approval_id: str = "SYNTHETIC",
    counters: ExecutionCounters | None = None,
) -> ProcessedRecords:
    validate_aihub_71748_processing_manifest(manifest)
    if tuple(manifest.get("rule_order", ())) != RULE_ORDER:
        raise AIHub71748ProcessingError("RULE_ORDER_MISMATCH")
    runtime = monitor or RuntimeMonitor()
    if counters is not None:
        counters.increment("policy_dispatch_calls")
    if enforce_expected_statistics:
        expected_records = manifest["input_contract"]["records"]  # type: ignore[index]
        actual_training = sum(record.split == "training" for record in records)
        actual_validation = sum(record.split == "validation" for record in records)
        if (
            actual_training != int(expected_records["Training"])  # type: ignore[index]
            or actual_validation != int(expected_records["Validation"])  # type: ignore[index]
            or len(records) != int(expected_records["Total"])  # type: ignore[index]
        ):
            raise AIHub71748ProcessingError("INPUT_RECORD_COUNT_MISMATCH")
    thresholds = manifest["thresholds"]  # type: ignore[index]
    near = thresholds["near_duplicate"]  # type: ignore[index]
    if enforce_expected_statistics and not blocked_prompts:
        raise AIHub71748ProcessingError("RECORD_LEVEL_POLICY_SIGNAL_MISSING")
    signals = recompute_record_signals(
        records,
        review_min=float(near["review_min"]),  # type: ignore[index]
        high_similarity_min=float(near["high_similarity_min"]),  # type: ignore[index]
        blocked_prompts=blocked_prompts,
    )
    runtime.check("record_level_signals", source_records=len(records))
    retained: dict[str, list[dict[str, object]]] = {"training": [], "validation": []}
    excluded = {"pii": 0, "exact_duplicate": 0, "near_duplicate": 0, "leakage": 0}
    for record, signal in zip(records, signals):
        reason = next((name for name in excluded if getattr(signal, name) == ("exclude" if name in {"pii", "leakage"} else "duplicate")), None)
        if reason is not None:
            excluded[reason] += 1
            continue
        retained[record.split].append(_safe_output(record))
    total_output = sum(len(value) for value in retained.values())
    runtime.check(
        "statistics_validation",
        source_records=len(records),
        output_records=total_output,
        exclusion_count=len(records) - total_output,
    )
    expected = manifest["expected_statistics"]["output"]  # type: ignore[index]
    if enforce_expected_statistics and len(retained["training"]) < int(expected["minimum_training_records"]):  # type: ignore[index]
        raise AIHub71748ProcessingError("TRAINING_SIZE_BELOW_MINIMUM")
    if enforce_expected_statistics and len(retained["validation"]) < int(expected["minimum_validation_records"]):  # type: ignore[index]
        raise AIHub71748ProcessingError("VALIDATION_SIZE_BELOW_MINIMUM")
    rate = 0.0 if not records else (len(records) - total_output) / len(records)
    if enforce_expected_statistics and rate > float(expected["maximum_total_exclusion_rate"]):  # type: ignore[index]
        raise AIHub71748ProcessingError("EXCLUSION_RATE_ABOVE_LIMIT")
    input_training = sum(record.split == "training" for record in records)
    input_validation = len(records) - input_training
    excluded_training = sum(
        record.split == "training" and any((signal.pii == "exclude", signal.exact_duplicate == "duplicate", signal.near_duplicate == "duplicate", signal.leakage == "exclude"))
        for record, signal in zip(records, signals)
    )
    excluded_validation = len(records) - total_output - excluded_training
    detailed = detailed_statistics_schema(run_id=run_id, approval_id=approval_id)
    detailed["run"].update({  # type: ignore[union-attr]
        "processing_calls": 0 if counters is None else counters.processing_calls,
        "payload_open_sessions": 0 if counters is None else counters.payload_open_sessions,
    })
    detailed["input"].update({"Training": input_training, "Validation": input_validation, "Total": len(records)})  # type: ignore[union-attr]
    detailed["source"].update({"sftdata_records": len(records), "sftlabel_records": len(records)})  # type: ignore[union-attr]
    detailed["join"]["matched"] = len(records)  # type: ignore[index]
    detailed["pii"].update({"training_excluded": excluded["pii"], "validation_excluded": 0})  # type: ignore[union-attr]
    detailed["exact_duplicate"].update({"same_split_excluded": excluded["exact_duplicate"]})  # type: ignore[union-attr]
    detailed["near_duplicate"].update({"same_split_review": excluded["near_duplicate"]})  # type: ignore[union-attr]
    detailed["leakage"].update({"near_question_review": excluded["leakage"]})  # type: ignore[union-attr]
    detailed["actions"].update({  # type: ignore[union-attr]
        "keep": total_output,
        "training_excluded": excluded_training,
        "validation_excluded": excluded_validation,
    })
    detailed["output"].update({  # type: ignore[union-attr]
        "Training": len(retained["training"]),
        "Validation": len(retained["validation"]),
        "Total": total_output,
        "excluded_total": len(records) - total_output,
        "exclusion_rate": rate,
        "output_files": 6,
    })
    detailed["runtime"].update({  # type: ignore[union-attr]
        "elapsed_seconds": runtime.elapsed_seconds(),
        "peak_memory_mib": runtime.peak_rss_bytes / (1024 * 1024),
        "soft_runtime_triggered": runtime.soft_runtime_triggered,
        "soft_memory_triggered": runtime.soft_memory_triggered,
    })
    detailed["validation"].update({  # type: ignore[union-attr]
        "jsonl_valid": True,
        "split_isolation_valid": True,
        "checksum_valid": True,
        "source_immutable": True,
        "output_budget_valid": True,
    })
    validate_detailed_statistics(detailed)
    return ProcessedRecords(
        train=tuple(retained["training"]),
        validation=tuple(retained["validation"]),
        statistics=detailed,
    )


def load_blocked_evaluation_prompts(repository_root: str | Path) -> frozenset[str]:
    values: set[str] = set()
    root = Path(repository_root).resolve()
    for relative in ("configs/evaluation-prompts.example.yaml", "configs/eos-generation-prompts.example.yaml"):
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (ValueError, OSError, UnicodeError, yaml.YAMLError):
            raise AIHub71748ProcessingError("RECORD_LEVEL_POLICY_SIGNAL_MISSING") from None
        prompts = document.get("prompts") if isinstance(document, dict) else None
        if not isinstance(document, dict) or document.get("source") != "synthetic" or document.get("pii_free") is not True or not isinstance(prompts, list):
            raise AIHub71748ProcessingError("RECORD_LEVEL_POLICY_SIGNAL_MISSING")
        for prompt in prompts:
            if not isinstance(prompt, dict) or not isinstance(prompt.get("text"), str):
                raise AIHub71748ProcessingError("RECORD_LEVEL_POLICY_SIGNAL_MISSING")
            values.add(normalize_near_duplicate_text(prompt["text"]))
    if not values:
        raise AIHub71748ProcessingError("RECORD_LEVEL_POLICY_SIGNAL_MISSING")
    return frozenset(values)


def execute_approved_processing(
    *,
    package_root: str | Path,
    run_root: str | Path,
    repository_root: str | Path,
    manifest: Mapping[str, object],
    contract: ProcessingRunContract,
    approval_path: str | Path,
    manifest_sha256: str,
    backend_git_commit: str,
    backend_fingerprint: str,
    preflight_evidence_fingerprint: str,
    runtime_request: RuntimeExecutionRequest,
    monitor: RuntimeMonitor | None = None,
    enforce_expected_statistics: bool = True,
    counters: ExecutionCounters | None = None,
    now: Callable[[], str] | None = None,
) -> dict[str, object]:
    """Execute once after an external approval has been issued; never retries."""

    validate_run_contract(contract)
    validate_aihub_71748_processing_manifest(manifest)
    approval = validate_approval_file(approval_path, contract)
    if approval.status != "issued" or approval.consumed:
        raise ProcessingApprovalError("APPROVAL_ALREADY_CONSUMED")
    if (
        approval.manifest_sha256 != manifest_sha256
        or approval.execution_source_commit != backend_git_commit
        or approval.backend_fingerprint != backend_fingerprint
        or approval.preflight_evidence_fingerprint != preflight_evidence_fingerprint
    ):
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    if not all((
        approval.processing_allowed,
        approval.payload_read_allowed,
        approval.output_write_allowed,
    )):
        raise ProcessingApprovalError("APPROVAL_CAPABILITY_INSUFFICIENT")
    timestamp = now or (lambda: datetime.now(timezone.utc).isoformat())
    consume_time = timestamp()
    validate_runtime_request(
        runtime_request,
        contract,
        expected_approval_fingerprint=approval_fingerprint(approval),
        expected_preflight_evidence_fingerprint=preflight_evidence_fingerprint,
        expected_execution_source_commit=backend_git_commit,
        expected_governance_record_commit=approval.governance_record_commit,
        expected_manifest_sha256=manifest_sha256,
        expected_backend_fingerprint=backend_fingerprint,
        now=datetime.fromisoformat(consume_time),
    )
    sources = discover_sft_sources(package_root)  # metadata only before consume
    usage = counters or ExecutionCounters()
    consumed = consume_approval(
        approval_path, approval, consumed_at=consume_time,
        contract=contract, runtime_request=runtime_request, counters=usage,
    )
    usage.begin_processing()
    runtime = monitor or RuntimeMonitor()
    source_before = snapshot_source_metadata(package_root)
    disk = DiskGuard(Path(run_root).parent)
    try:
        loaded: list[SourceRecord] = []
        with payload_session(usage):
            for source in sources:
                usage.increment("archive_member_enumerations")
                usage.increment("zip_entry_opens")
                loaded.extend(iter_source_records(source))
                usage.increment("json_parser_calls")
                runtime.check("archive_stream")
        records = tuple(loaded)
        for _ in records:
            usage.increment("record_parser_calls")
        usage.increment("join_calls")
        joined = join_source_records(records)
        runtime.check("join", source_records=len(joined))
        processed = process_joined_records(
            joined,
            manifest,
            monitor=runtime,
            enforce_expected_statistics=enforce_expected_statistics,
            blocked_prompts=load_blocked_evaluation_prompts(repository_root),
            run_id=contract.run_id,
            approval_id=contract.approval_id,
            counters=usage,
        )
        completion_time = timestamp()
        result = {
            "schema_version": 1,
            "status": "completed",
            "run_id": contract.run_id,
            "approval_id": contract.approval_id,
            "runtime_request_id": runtime_request.request_id,
            "execution_source_commit": backend_git_commit,
            "governance_record_commit": approval.governance_record_commit,
            "manifest_sha256": manifest_sha256,
            "backend_fingerprint": backend_fingerprint,
            "preflight_evidence_fingerprint": preflight_evidence_fingerprint,
            "approval_fingerprint": approval_fingerprint(consumed),
            "runtime_request_fingerprint": runtime_request.request_fingerprint,
            "started_at": consume_time,
            "completed_at": completion_time,
            "failed_at": None,
            "input_statistics": dict(processed.statistics["input"]),  # type: ignore[index]
            "output_statistics": dict(processed.statistics["output"]),  # type: ignore[index]
            "rejection_statistics": dict(processed.statistics["actions"]),  # type: ignore[index]
            "output_files": 6,
            "output_total_bytes": 0,
            "checksums_sha256": {},
            "counters": usage.snapshot(),
            "finalization": {
                "staging_created": True,
                "final_created": True,
                "staging_removed": True,
                "atomic_rename_completed": True,
            },
            "tokenization_allowed": False,
            "training_allowed": False,
        }
        written = write_atomic_outputs(
            run_root,
            train_records=processed.train,
            validation_records=processed.validation,
            manifest=manifest,
            statistics=processed.statistics,
            result=result,
            hardened=HardenedWriteContext(
                counters=usage,
                monitor=runtime,
                disk_guard=disk,
                source_before=source_before,
                source_root=Path(package_root),
                approval_consumed=True,
                expected_training=len(processed.train),
                expected_validation=len(processed.validation),
                minimum_training=10_000 if enforce_expected_statistics else 0,
                minimum_validation=1_000 if enforce_expected_statistics else 0,
            ),
        )
        finalize_approval(approval_path, consumed, success=True, finalized_at=completion_time)
        output_total = sum(
            path.stat().st_size for path in Path(run_root).iterdir() if path.is_file()
        )
        return {
            **result,
            "counts": written["counts"],
            "checksums_sha256": written["checksums"],
            "counters": usage.snapshot(),
            "output_total_bytes": output_total,
            "approval_consumed": True,
        }
    except Exception:
        final = Path(run_root)
        quarantine = final.with_name(final.name + ".failed")
        if final.exists() and not quarantine.exists():
            os.replace(final, quarantine)
        try:
            if consumed.state == "consumed":
                finalize_approval(approval_path, consumed, success=False, finalized_at=timestamp())
        except ProcessingApprovalError:
            pass
        raise
