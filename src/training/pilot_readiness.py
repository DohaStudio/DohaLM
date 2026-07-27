"""Fail-closed readiness contract for a real tokenizer/corpus pilot."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from src.data.checksums import checksum_value

from .errors import TrainingError


BLOCKER_MESSAGES = {
    "GATE3_NOT_PASSED": "Gate 3가 passed가 아닙니다.",
    "GATE4_NOT_PASSED": "Gate 4가 passed가 아닙니다.",
    "GATE5_NOT_PASSED": "Gate 5가 passed가 아닙니다.",
    "GATE6_NOT_PASSED": "Gate 6가 passed가 아닙니다.",
    "GATE7_POLICY_NOT_SATISFIED": "Gate 7 또는 승인된 pilot 정책 조건이 충족되지 않았습니다.",
    "TOKENIZER_NOT_APPROVED": "운영 tokenizer가 승인되지 않았습니다.",
    "TOKENIZER_FINGERPRINT_MISSING": "tokenizer fingerprint가 없습니다.",
    "TOKENIZER_VOCAB_MISMATCH": "tokenizer vocabulary가 16,000이 아닙니다.",
    "SPECIAL_TOKEN_IDS_INVALID": "special token ID 0~7 계약이 확인되지 않았습니다.",
    "CORPUS_NOT_APPROVED": "pilot corpus의 목적별 승인이 없습니다.",
    "LICENSE_NOT_APPROVED": "corpus 라이선스가 승인되지 않았습니다.",
    "PII_NOT_CLEARED": "PII 상태가 clear 또는 승인된 conditional이 아닙니다.",
    "CORPUS_MANIFEST_MISSING": "corpus manifest/checksum이 없습니다.",
    "SPLIT_NOT_VERIFIED": "train/validation split이 검증되지 않았습니다.",
    "EVALUATION_EXCLUSION_MISSING": "evaluation 제외 증거가 없습니다.",
    "DATASET_FINGERPRINT_MISSING": "dataset fingerprint가 없습니다.",
    "SOURCE_LINEAGE_NOT_VERIFIED": "Pilot source selection이 승인된 corpus 계보와 일치하지 않습니다.",
    "RUNTIME_REVALIDATION_REQUIRED": "검증된 Pilot dataset identity에 대한 별도 runtime 재검증 승인이 필요합니다.",
    "STORAGE_NOT_VERIFIED": "출력 저장공간이 검증되지 않았습니다.",
    "CHECKPOINT_RETENTION_NOT_APPROVED": "checkpoint 보존 정책이 승인되지 않았습니다.",
    "TRAINING_CONFIG_NOT_APPROVED": "training config가 승인되지 않았습니다.",
    "SCHEDULER_NOT_APPROVED": "scheduler가 승인되지 않았습니다.",
    "BATCH_POLICY_NOT_APPROVED": "batch/accumulation 정책이 승인되지 않았습니다.",
    "ESTIMATE_NOT_VERIFIED": "예상 시간/VRAM 범위가 검증되지 않았습니다.",
    "RESUME_PROCEDURE_MISSING": "중단/resume 절차가 없습니다.",
}


def _is_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def evaluate_pilot_readiness(value: dict[str, Any]) -> dict[str, Any]:
    gates = value.get("gates", {}) if isinstance(value.get("gates"), dict) else {}
    tokenizer = value.get("tokenizer", {}) if isinstance(value.get("tokenizer"), dict) else {}
    corpus = value.get("corpus", {}) if isinstance(value.get("corpus"), dict) else {}
    training = value.get("training", {}) if isinstance(value.get("training"), dict) else {}
    storage = value.get("storage", {}) if isinstance(value.get("storage"), dict) else {}
    failures: list[str] = []

    for gate in (3, 4, 5, 6):
        if gates.get(str(gate)) != "passed":
            failures.append(f"GATE{gate}_NOT_PASSED")
    if gates.get("7") != "passed" and gates.get("pilot_policy") != "approved":
        failures.append("GATE7_POLICY_NOT_SATISFIED")
    if tokenizer.get("approval_status") != "approved":
        failures.append("TOKENIZER_NOT_APPROVED")
    if not _is_fingerprint(tokenizer.get("fingerprint")):
        failures.append("TOKENIZER_FINGERPRINT_MISSING")
    if tokenizer.get("vocab_size") != 16_000:
        failures.append("TOKENIZER_VOCAB_MISMATCH")
    if tokenizer.get("special_token_ids") != list(range(8)):
        failures.append("SPECIAL_TOKEN_IDS_INVALID")
    if corpus.get("approval_status") != "approved_pilot_pretraining":
        failures.append("CORPUS_NOT_APPROVED")
    if corpus.get("license_status") not in ("approved", "approved_student_noncommercial"):
        failures.append("LICENSE_NOT_APPROVED")
    if corpus.get("pii_status") not in ("clear", "approved_conditional"):
        failures.append("PII_NOT_CLEARED")
    if not _is_fingerprint(corpus.get("manifest_checksum")):
        failures.append("CORPUS_MANIFEST_MISSING")
    if corpus.get("split_verified") is not True:
        failures.append("SPLIT_NOT_VERIFIED")
    if corpus.get("evaluation_exclusion_verified") is not True:
        failures.append("EVALUATION_EXCLUSION_MISSING")
    if not _is_fingerprint(corpus.get("dataset_fingerprint")):
        failures.append("DATASET_FINGERPRINT_MISSING")
    if corpus.get("source_lineage_verified") is not True:
        failures.append("SOURCE_LINEAGE_NOT_VERIFIED")
    if training.get("runtime_smoke_dataset_fingerprint") != corpus.get("dataset_fingerprint"):
        failures.append("RUNTIME_REVALIDATION_REQUIRED")
    if storage.get("verified") is not True:
        failures.append("STORAGE_NOT_VERIFIED")
    if training.get("checkpoint_retention_approved") is not True:
        failures.append("CHECKPOINT_RETENTION_NOT_APPROVED")
    if training.get("config_approved") is not True:
        failures.append("TRAINING_CONFIG_NOT_APPROVED")
    if training.get("scheduler_approved") is not True:
        failures.append("SCHEDULER_NOT_APPROVED")
    if training.get("batch_policy_approved") is not True:
        failures.append("BATCH_POLICY_NOT_APPROVED")
    if training.get("estimate_verified") is not True:
        failures.append("ESTIMATE_NOT_VERIFIED")
    if training.get("resume_procedure_documented") is not True:
        failures.append("RESUME_PROCEDURE_MISSING")

    only_runtime_revalidation = failures == ["RUNTIME_REVALIDATION_REQUIRED"]
    result = {
        "schema_version": "1.0",
        "status": (
            "ready_for_user_approval" if not failures
            else "ready_awaiting_runtime_revalidation_and_final_execution_approval" if only_runtime_revalidation
            else "blocked"
        ),
        "eligible": not failures,
        "blocking_reasons": [{"code": code, "message": BLOCKER_MESSAGES[code]} for code in failures],
        "user_approval_required": True,
        "approved_by": None,
        "approved_at": None,
    }
    result["evidence_fingerprint"] = checksum_value(result)
    return result


def _gate_statuses(roadmap: Path) -> dict[str, str]:
    try:
        source = roadmap.read_text(encoding="utf-8")
    except OSError as exc:
        raise TrainingError("PILOT_READINESS_INPUT_INVALID", "개발 로드맵을 읽을 수 없습니다.") from exc
    statuses: dict[str, str] = {}
    for gate in range(3, 8):
        match = re.search(rf"\| Gate {gate}:[^\n]*\| `([^`]+)` \|", source)
        statuses[str(gate)] = match.group(1) if match else "unknown"
    return statuses


def readiness_input_from_config(config_path: Path, roadmap_path: Path) -> dict[str, Any]:
    try:
        document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TrainingError("PILOT_READINESS_INPUT_INVALID", "pretraining config를 읽을 수 없습니다.") from exc
    if not isinstance(document, dict):
        raise TrainingError("PILOT_READINESS_INPUT_INVALID", "pretraining config의 최상위 값은 object여야 합니다.")
    explicit = document.get("pilot_readiness", {})
    if explicit is None:
        explicit = {}
    if not isinstance(explicit, dict):
        raise TrainingError("PILOT_READINESS_INPUT_INVALID", "pilot_readiness 값은 object여야 합니다.")
    return {
        "gates": {**_gate_statuses(roadmap_path), **(explicit.get("gates", {}) if isinstance(explicit.get("gates"), dict) else {})},
        "tokenizer": explicit.get("tokenizer", {}),
        "corpus": explicit.get("corpus", {}),
        "training": explicit.get("training", {}),
        "storage": explicit.get("storage", {}),
    }


def validate_pilot_readiness(config_path: Path, roadmap_path: Path) -> dict[str, Any]:
    return evaluate_pilot_readiness(readiness_input_from_config(config_path, roadmap_path))
