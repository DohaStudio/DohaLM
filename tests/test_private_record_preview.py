from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from scripts.datasets import private_record_preview
from scripts.datasets.analyzer import AnalyzerConfig, DatasetEntry
from scripts.datasets.manual_path_mapping import load_manual_mapping
from scripts.datasets.private_preview_policy import load_private_preview_policy
from scripts.datasets.private_preview_review import inspect_private_review
from scripts.datasets.private_record_preview import (
    TRUNCATION_MARKER,
    generate_private_previews,
    limit_text,
    private_review_output_root,
    redact_text,
    select_preview_options,
)
from scripts.datasets.safe_sampler import SamplerError


def _write_policy(path: Path, *, status: str = "approved", **scope_changes: object) -> Path:
    approved = status == "approved"
    scope = {
        "purpose": "manual_pii_and_quality_review",
        "max_records": 5,
        "allowed_fields": ["text"],
        "max_characters_per_record": 300,
        "retention_days": 3,
        "allow_unredacted": False,
    }
    scope.update(scope_changes)
    data = {
        "schema_version": "1.0",
        "dataset_id": "AIHUB-71748",
        "approval": {
            "status": status,
            "approved_by": "tester" if approved else None,
            "approved_at": "2026-07-24T00:00:00+09:00" if approved else None,
            "expires_at": "2099-07-31T00:00:00+09:00" if approved else None,
        },
        "scope": scope,
        "review": {
            "reviewer": "reviewer" if approved else None,
            "output_root": "external_private_review_root",
        },
    }
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _write_mapping(path: Path) -> Path:
    path.write_text(
        """schema_version: "1.0"
dataset_id: "AIHUB-71748"
approval:
  status: approved
  approved_by: tester
  approved_at: "2026-07-24T00:00:00+09:00"
rules:
  - source_prefix: "/approved/"
    target_prefix: "mapped/"
    allowed_extensions: [.json]
""",
        encoding="utf-8",
    )
    return path


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, archives: int = 2):
    external = tmp_path / "external"
    source = external / "source"
    source.mkdir(parents=True)
    texts = [
        "홍길동 test@example.com 010-1234-5678 900101-1234567 4111-1111-1111-1111",
        "IP 192.168.0.1 ID 123456789012 URL https://example.test/p?q=secret",
        "한글 문장 " * 80,
    ]
    zip_paths = []
    for archive_index in range(archives):
        path = source / f"archive-{archive_index}.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                f"/approved/entry-{archive_index}.json",
                json.dumps([{"text": text, "metadata": {"secret": "DO-NOT-SAVE"}} for text in texts]),
            )
        zip_paths.append(path)
    mapping = load_manual_mapping(_write_mapping(tmp_path / "mapping.yaml"), "AIHUB-71748")
    policy = load_private_preview_policy(
        _write_policy(tmp_path / "policy.yaml"), "AIHUB-71748", require_approved=True,
    )
    monkeypatch.setattr(private_record_preview, "DEFAULT_LARGE_THRESHOLD_BYTES", 0)
    entry = DatasetEntry("AIHUB-71748", "source", source)
    output = external / "analysis" / "private-review"
    return entry, output, mapping, policy, zip_paths


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_policy_pending_blocks_generation_and_allows_dry_run(tmp_path: Path):
    path = _write_policy(tmp_path / "policy.yaml", status="pending_user_review")
    with pytest.raises(SamplerError):
        load_private_preview_policy(path, "AIHUB-71748", require_approved=True)
    policy = load_private_preview_policy(path, "AIHUB-71748", require_approved=False)
    assert policy.approval.status == "pending_user_review"


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("allowed_fields", ["content"]),
        ("allow_unredacted", True),
        ("max_records", 11),
        ("max_characters_per_record", 501),
    ],
)
def test_policy_rejects_scope_outside_contract(tmp_path: Path, change: str, value: object):
    path = _write_policy(tmp_path / "policy.yaml", **{change: value})
    with pytest.raises(SamplerError):
        load_private_preview_policy(path, "AIHUB-71748", require_approved=True)


def test_policy_rejects_dataset_mismatch_and_expired_approval(tmp_path: Path):
    path = _write_policy(tmp_path / "policy.yaml")
    with pytest.raises(SamplerError):
        load_private_preview_policy(path, "OTHER", require_approved=True)
    with pytest.raises(SamplerError):
        load_private_preview_policy(
            path,
            "AIHUB-71748",
            require_approved=True,
            now=datetime(2100, 1, 1, tzinfo=UTC),
        )


def test_redaction_covers_required_patterns_without_raw_values():
    raw = (
        "mail test@example.com phone 010-1234-5678 rrn 900101-1234567 "
        "card 4111-1111-1111-1111 ip 192.168.0.1 id 123456789012 "
        "url https://example.test/path?token=raw"
    )
    redacted, types, count = redact_text(raw)
    assert set(types) == {"card", "email", "identifier", "ip", "phone", "rrn", "url_query"}
    assert count == 7
    assert all(secret not in redacted for secret in (
        "test@example.com", "010-1234-5678", "900101-1234567", "4111-1111-1111-1111",
        "192.168.0.1", "123456789012", "token=raw",
    ))


def test_unicode_limit_includes_marker_within_character_limit():
    stored, truncated = limit_text("가나다라마바사아자차카타파하", 13)
    assert truncated is True
    assert len(stored) == 13
    assert stored.endswith(TRUNCATION_MARKER)


def test_selection_is_deterministic_and_one_per_archive_entry():
    rows = [
        {
            "archive_hash": f"a-{archive}",
            "entry_hash": f"e-{entry}",
            "record_stratum": "head" if record == 0 else "tail",
            "schema_signature": f"sha256:{archive}{entry}",
            "selection_rank": f"{archive}{entry}{record}",
        }
        for archive in range(3) for entry in range(2) for record in range(2)
    ]
    first = select_preview_options(rows, 3)
    second = select_preview_options(reversed(rows), 3)
    assert first == second
    assert len({row["archive_hash"] for row in first}) == 3
    assert len({(row["archive_hash"], row["entry_hash"]) for row in first}) == 3


def test_generation_writes_only_redacted_minimal_preview_and_preserves_zip(tmp_path: Path, monkeypatch):
    entry, output, mapping, policy, zip_paths = _fixture(tmp_path, monkeypatch)
    before = [_sha256(path) for path in zip_paths]
    result = generate_private_previews(entry, output, mapping, policy, dry_run=False, selection_seed="fixed")
    run = output / entry.dataset_id / result["run_id"]
    manifest = json.loads((run / "preview-manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run / "run-summary.json").read_text(encoding="utf-8"))
    deletion = json.loads((run / "deletion-manifest.json").read_text(encoding="utf-8"))
    assert 1 <= manifest["preview_count"] <= len(zip_paths)
    assert summary["full_record_saved"] is False
    assert summary["metadata_values_saved"] is False
    assert deletion["deletion_required"] is True
    for preview in manifest["previews"]:
        content = (run / f"{preview['preview_id']}.txt").read_text(encoding="utf-8")
        assert "DO-NOT-SAVE" not in content
        assert "metadata" not in content
        assert len(content.split("---\n", 1)[1].rstrip("\n")) <= policy.scope.max_characters_per_record
    assert before == [_sha256(path) for path in zip_paths]
    assert all(str(entry.root.resolve()) not in path.read_text(encoding="utf-8") for path in run.glob("*.json"))
    with pytest.raises(SamplerError):
        generate_private_previews(entry, output, mapping, policy, dry_run=False, selection_seed="fixed")


def test_dry_run_reads_no_entry_content_and_creates_no_preview(tmp_path: Path, monkeypatch):
    entry, output, mapping, _, _ = _fixture(tmp_path, monkeypatch)
    policy = load_private_preview_policy(
        _write_policy(tmp_path / "pending.yaml", status="pending_user_review"),
        "AIHUB-71748",
        require_approved=False,
    )
    original_open = zipfile.ZipFile.open

    def forbidden_read(self, name, mode="r", *args, **kwargs):
        if mode == "r":
            raise AssertionError("dry-run must not open ZIP entry content")
        return original_open(self, name, mode, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", forbidden_read)
    result = generate_private_previews(entry, output, mapping, policy, dry_run=True)
    run = output / entry.dataset_id / result["run_id"]
    assert result["run_status"] == "dry_run_blocked_pending_approval"
    assert result["total_bytes_read"] == 0
    assert not list(run.glob("*.txt"))
    assert {path.name for path in run.iterdir()} == {
        "preview-manifest.json", "review-checklist.json", "deletion-manifest.json", "run-summary.json",
    }
    expiration = inspect_private_review(run, tmp_path / "repo", check_expiration=True)
    assert expiration["review_completion_allowed"] is False
    with pytest.raises(SamplerError):
        inspect_private_review(run, tmp_path / "repo", check_expiration=False)


def test_output_boundary_blocks_repository_and_source(tmp_path: Path):
    external = tmp_path / "external"
    source = external / "source"
    source.mkdir(parents=True)
    config = AnalyzerConfig(external, {"AIHUB-71748": DatasetEntry("AIHUB-71748", "source", source)})
    repository = tmp_path / "repo"
    repository.mkdir()
    with pytest.raises(SamplerError):
        private_review_output_root(config, repository, repository)
    with pytest.raises(SamplerError):
        private_review_output_root(config, source, repository)


def test_review_validation_checks_notes_expiration_and_manifest(tmp_path: Path, monkeypatch):
    entry, output, mapping, policy, _ = _fixture(tmp_path, monkeypatch, archives=1)
    result = generate_private_previews(entry, output, mapping, policy, dry_run=False)
    run = output / entry.dataset_id / result["run_id"]
    inspection = inspect_private_review(run, tmp_path / "repo", check_expiration=False)
    assert inspection["automatic_pii_clear"] is False
    checklist_path = run / "review-checklist.json"
    checklist = json.loads(checklist_path.read_text(encoding="utf-8"))
    checklist["items"][0]["reviewer_note"] = "원문\n복사 금지"
    checklist_path.write_text(json.dumps(checklist, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SamplerError):
        inspect_private_review(run, tmp_path / "repo", check_expiration=False)
    expiration = inspect_private_review(
        run, tmp_path / "repo", check_expiration=True, now=datetime(2100, 1, 1, tzinfo=UTC),
    )
    assert expiration["expired"] is True
    assert expiration["review_completion_allowed"] is False
