"""외부 private preview review bundle의 만료·checksum·수동 결과를 검증한다."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .safe_sampler import SamplerError, _sha256_file


DECISIONS = frozenset({"not_reviewed", "clear", "conditional", "blocked"})
BOOLEAN_REVIEW_FIELDS = (
    "pii_detected",
    "sensitive_information_detected",
    "coherent_korean_text",
    "corrupted_text",
    "boilerplate_or_template",
    "duplicate_or_repeated",
    "suitable_for_tokenizer",
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SamplerError("private review JSON을 안전하게 읽을 수 없습니다.") from exc
    if not isinstance(value, dict):
        raise SamplerError("private review JSON 최상위는 object여야 합니다.")
    return value


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise SamplerError(f"{field}이 누락됐습니다.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SamplerError(f"{field} 형식이 올바르지 않습니다.") from exc
    if parsed.tzinfo is None:
        raise SamplerError(f"{field}에는 timezone이 필요합니다.")
    return parsed.astimezone(UTC)


def _validate_review_directory(review_dir: Path, repository_root: Path) -> Path:
    resolved = review_dir.resolve()
    repository = repository_root.resolve()
    if resolved == repository or repository in resolved.parents:
        raise SamplerError("Git 저장소 내부 private review 경로는 허용하지 않습니다.")
    if not resolved.is_dir():
        raise SamplerError("private review run 디렉터리가 존재하지 않습니다.")
    return resolved


def inspect_private_review(
    review_dir: Path,
    repository_root: Path,
    *,
    check_expiration: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = _validate_review_directory(review_dir, repository_root)
    required = {
        "preview-manifest.json", "review-checklist.json", "deletion-manifest.json", "run-summary.json",
    }
    missing = sorted(name for name in required if not (root / name).is_file())
    if missing:
        raise SamplerError("private review 필수 manifest가 누락됐습니다.")
    manifest = _load_json(root / "preview-manifest.json")
    checklist = _load_json(root / "review-checklist.json")
    deletion = _load_json(root / "deletion-manifest.json")
    summary = _load_json(root / "run-summary.json")
    identity = (manifest.get("dataset_id"), manifest.get("run_id"))
    if any((document.get("dataset_id"), document.get("run_id")) != identity for document in (checklist, deletion, summary)):
        raise SamplerError("private review manifest identity가 서로 일치하지 않습니다.")

    expires_raw = manifest.get("expires_at")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    expired = False if expires_raw is None else current >= _parse_timestamp(expires_raw, "expires_at")
    review_completion_allowed = (
        not expired
        and summary.get("mode") == "generation"
        and summary.get("approval_status") == "approved"
        and manifest.get("preview_count", 0) > 0
    )
    if check_expiration:
        return {
            "success": True,
            "dataset_id": identity[0],
            "run_id": identity[1],
            "expired": expired,
            "deletion_required": bool(deletion.get("deletion_required")),
            "deletion_verification_status": deletion.get("deletion_verification_status"),
            "review_completion_allowed": review_completion_allowed,
        }
    if expired:
        raise SamplerError("private preview 보존 기한이 만료돼 review 완료를 처리할 수 없습니다.")
    if not review_completion_allowed:
        raise SamplerError("실제 승인으로 생성된 preview가 아니므로 review를 완료할 수 없습니다.")

    previews = manifest.get("previews")
    items = checklist.get("items")
    if not isinstance(previews, list) or not isinstance(items, list):
        raise SamplerError("preview manifest 또는 review checklist 형식이 올바르지 않습니다.")
    preview_ids = {row.get("preview_id") for row in previews if isinstance(row, dict)}
    item_ids = {row.get("preview_id") for row in items if isinstance(row, dict)}
    if len(preview_ids) != len(previews) or preview_ids != item_ids:
        raise SamplerError("preview와 review checklist ID가 일치하지 않습니다.")

    for row in previews:
        preview_id = row["preview_id"]
        path = root / f"{preview_id}.txt"
        if not path.is_file() or _sha256_file(path) != row.get("preview_checksum"):
            raise SamplerError("private preview 파일 checksum이 일치하지 않습니다.")

    decisions: Counter[str] = Counter()
    completed = 0
    for item in items:
        decision = item.get("decision")
        if decision not in DECISIONS:
            raise SamplerError("review decision이 허용 상태와 일치하지 않습니다.")
        note = item.get("reviewer_note")
        if note is not None and (not isinstance(note, str) or len(note) > 500 or "\n" in note or "\r" in note):
            raise SamplerError("reviewer_note는 원문 복사를 줄이도록 500자 이하 단일 행이어야 합니다.")
        if decision != "not_reviewed":
            if any(not isinstance(item.get(field), bool) for field in BOOLEAN_REVIEW_FIELDS):
                raise SamplerError("완료된 review에는 모든 boolean 검토 결과가 필요합니다.")
            if not isinstance(item.get("reviewed_by"), str) or not item["reviewed_by"].strip():
                raise SamplerError("완료된 review에는 reviewed_by가 필요합니다.")
            _parse_timestamp(item.get("reviewed_at"), "reviewed_at")
            completed += 1
        decisions[decision] += 1

    return {
        "success": True,
        "dataset_id": identity[0],
        "run_id": identity[1],
        "expired": False,
        "preview_count": len(previews),
        "reviews_completed": completed,
        "reviews_pending": len(previews) - completed,
        "decision_counts": dict(sorted(decisions.items())),
        "automatic_pii_clear": False,
        "license_approval_effect": "none",
        "tokenizer_approval_effect": "none",
    }
