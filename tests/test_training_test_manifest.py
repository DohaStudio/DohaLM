from __future__ import annotations

import json
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from scripts.ci.training_test_manifest import (
    ManifestError,
    emit_required,
    validate_manifest,
)


@pytest.fixture
def isolated_repository() -> Iterator[Path]:
    with TemporaryDirectory(prefix="dohalm-training-manifest-") as directory:
        yield Path(directory)


def _test_file(
    root: Path, name: str, source: str = "def test_example():\n    pass\n"
) -> str:
    path = root / "tests" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path.relative_to(root).as_posix()


def _entry(
    path: str,
    *,
    tier: str = "required_cpu",
    required: bool = True,
    group: str | None = "critical",
    owner: str = "training",
    reason: str = "Synthetic manifest contract.",
) -> dict[str, object]:
    return {
        "path": path,
        "tier": tier,
        "owner": owner,
        "required": required,
        "reason": reason,
        "group": group,
    }


def _manifest(root: Path, entries: list[dict[str, object]]) -> Path:
    path = root / "manifest.json"
    path.write_text(
        json.dumps({"schema_version": 1, "tests": entries}, sort_keys=True),
        encoding="utf-8",
    )
    return path


def test_repository_manifest_is_complete() -> None:
    root = Path(__file__).resolve().parents[1]
    inventory = validate_manifest(root, root / ".github/ci/training-test-manifest.json")
    assert set(inventory.candidates) <= {entry.path for entry in inventory.entries}
    delegated = [entry for entry in inventory.entries if entry.tier == "delegated"]
    assert len(inventory.required) == 32
    assert [(entry.path, entry.owner) for entry in delegated] == [
        ("tests/test_postgres_c1.py", "c1"),
        ("tests/test_postgres_c1_integration.py", "c1"),
        ("tests/test_postgres_c2.py", "c2"),
        ("tests/test_postgres_c2_integration.py", "c2"),
        ("tests/test_postgres_c3.py", "c2"),
        ("tests/test_postgres_c3_integration.py", "c2"),
        ("tests/test_postgres_training_intent_authority.py", "c2"),
    ]


def test_unclassified_training_candidate_fails(isolated_repository: Path) -> None:
    classified = _test_file(isolated_repository, "test_training_classified.py")
    _test_file(
        isolated_repository, "test_other_contract.py", "import src." + "training\n"
    )
    with pytest.raises(ManifestError, match="unclassified Training candidates"):
        validate_manifest(
            isolated_repository,
            _manifest(isolated_repository, [_entry(classified)]),
        )


def test_stale_manifest_entry_fails(isolated_repository: Path) -> None:
    with pytest.raises(ManifestError, match="stale path"):
        validate_manifest(
            isolated_repository,
            _manifest(isolated_repository, [_entry("tests/test_training_stale.py")]),
        )


def test_duplicate_entry_fails(isolated_repository: Path) -> None:
    path = _test_file(isolated_repository, "test_training_duplicate.py")
    with pytest.raises(ManifestError, match="duplicate test entries"):
        validate_manifest(
            isolated_repository,
            _manifest(isolated_repository, [_entry(path), _entry(path)]),
        )


def test_unknown_tier_fails(isolated_repository: Path) -> None:
    path = _test_file(isolated_repository, "test_training_unknown.py")
    with pytest.raises(ManifestError, match="unknown tier"):
        validate_manifest(
            isolated_repository,
            _manifest(isolated_repository, [_entry(path, tier="unknown")]),
        )


def test_unknown_delegated_owner_fails(isolated_repository: Path) -> None:
    required = _test_file(isolated_repository, "test_training_required.py")
    delegated = _test_file(
        isolated_repository,
        "test_postgres_c1.py",
        "import src." + "training\n",
    )
    entries = [
        _entry(required),
        _entry(
            delegated,
            tier="delegated",
            required=False,
            group=None,
            owner="unknown",
        ),
    ]
    entries.sort(key=lambda entry: str(entry["path"]))
    with pytest.raises(ManifestError, match="unknown delegated owner"):
        validate_manifest(isolated_repository, _manifest(isolated_repository, entries))


def test_delegated_test_missing_from_upstream_pytest_fails(
    isolated_repository: Path,
) -> None:
    required = _test_file(isolated_repository, "test_training_required.py")
    delegated = _test_file(
        isolated_repository,
        "test_postgres_c1.py",
        "import src." + "training\n",
    )
    workflow = isolated_repository / ".github/workflows/c1-postgres-contract.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n  contract:\n    name: C1 PostgreSQL Contract\n"
        "    classifier: tests/test_postgres_c1*.py\n",
        encoding="utf-8",
    )
    entries = [
        _entry(required),
        _entry(
            delegated,
            tier="delegated",
            required=False,
            group=None,
            owner="c1",
        ),
    ]
    entries.sort(key=lambda entry: str(entry["path"]))
    with pytest.raises(ManifestError, match="not an upstream pytest target"):
        validate_manifest(isolated_repository, _manifest(isolated_repository, entries))


def test_delegated_test_missing_from_upstream_classifier_fails(
    isolated_repository: Path,
) -> None:
    required = _test_file(isolated_repository, "test_training_required.py")
    delegated = _test_file(
        isolated_repository,
        "test_postgres_c1.py",
        "import src." + "training\n",
    )
    workflow = isolated_repository / ".github/workflows/c1-postgres-contract.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n  contract:\n    name: C1 PostgreSQL Contract\n"
        "    run: python -m pytest tests/test_postgres_c1.py -q\n",
        encoding="utf-8",
    )
    entries = [
        _entry(required),
        _entry(
            delegated,
            tier="delegated",
            required=False,
            group=None,
            owner="c1",
        ),
    ]
    entries.sort(key=lambda entry: str(entry["path"]))
    with pytest.raises(ManifestError, match="not covered by upstream classifier"):
        validate_manifest(isolated_repository, _manifest(isolated_repository, entries))


def test_missing_owner_and_reason_fail(isolated_repository: Path) -> None:
    path = _test_file(isolated_repository, "test_training_fields.py")
    entry = _entry(path, owner="", reason="")
    with pytest.raises(ManifestError, match="owner must be a non-empty string"):
        validate_manifest(isolated_repository, _manifest(isolated_repository, [entry]))


def test_required_entry_emits_nul_delimited_path(isolated_repository: Path) -> None:
    path = _test_file(isolated_repository, "test_training_required.py")
    inventory = validate_manifest(
        isolated_repository,
        _manifest(isolated_repository, [_entry(path)]),
    )
    output = BytesIO()
    emit_required(inventory, "critical", output)
    assert output.getvalue() == path.encode("utf-8") + b"\0"


def test_non_required_candidate_is_classified_but_not_emitted(
    isolated_repository: Path,
) -> None:
    required = _test_file(isolated_repository, "test_training_required.py")
    entries = [_entry(required)]
    for tier in ("slow", "gpu", "external", "experimental", "historical", "optional"):
        path = _test_file(isolated_repository, f"test_training_{tier}.py")
        entries.append(_entry(path, tier=tier, required=False, group=None))
    entries.sort(key=lambda entry: str(entry["path"]))
    inventory = validate_manifest(
        isolated_repository,
        _manifest(isolated_repository, entries),
    )
    assert [entry.path for entry in inventory.required] == [required]


def test_unrelated_test_needs_no_manifest_entry(isolated_repository: Path) -> None:
    required = _test_file(isolated_repository, "test_training_required.py")
    _test_file(isolated_repository, "test_unrelated_contract.py")
    inventory = validate_manifest(
        isolated_repository,
        _manifest(isolated_repository, [_entry(required)]),
    )
    assert inventory.candidates == (required,)
