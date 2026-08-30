"""Validate and consume the Training required-test ownership manifest."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, TextIO

FILENAME_PATTERN = re.compile(r"(?:training|pretraining)", re.IGNORECASE)
CONTENT_MARKER = "src.training"
REQUIRED_TIER = "required_cpu"
DELEGATED_TIER = "delegated"
ALLOWED_TIERS = frozenset(
    {
        REQUIRED_TIER,
        DELEGATED_TIER,
        "slow",
        "gpu",
        "external",
        "experimental",
        "historical",
        "optional",
    }
)
ALLOWED_GROUPS = frozenset(
    {
        "local_activation",
        "continuation",
        "postgres_activation",
        "host",
        "critical",
        "manifest_guard",
    }
)
ENTRY_KEYS = frozenset({"path", "tier", "owner", "required", "reason", "group"})
DELEGATED_WORKFLOWS = {
    "c1": Path(".github/workflows/c1-postgres-contract.yml"),
    "c2": Path(".github/workflows/c2-postgres-training-adapters.yml"),
}
DELEGATED_CONTEXTS = {
    "c1": "C1 PostgreSQL Contract",
    "c2": "C2 PostgreSQL Training Adapters",
}
PYTEST_COMMAND = re.compile(
    r"^\s*(?:run:\s*)?python -m pytest\s+(?P<arguments>[^\r\n]+)$",
    re.MULTILINE,
)


class ManifestError(ValueError):
    """Raised when the ownership manifest is incomplete or contradictory."""


@dataclass(frozen=True)
class TestOwnership:
    path: str
    tier: str
    owner: str
    required: bool
    reason: str
    group: str | None


@dataclass(frozen=True)
class ManifestInventory:
    entries: tuple[TestOwnership, ...]
    candidates: tuple[str, ...]

    @property
    def required(self) -> tuple[TestOwnership, ...]:
        return tuple(entry for entry in self.entries if entry.required)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ManifestError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"cannot read manifest: {error}") from error


def discover_candidates(repository: Path) -> tuple[str, ...]:
    tests_root = repository / "tests"
    candidates: list[str] = []
    for path in sorted(tests_root.rglob("test_*.py")):
        relative = path.relative_to(repository).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ManifestError(
                f"cannot inspect candidate {relative}: {error}"
            ) from error
        if FILENAME_PATTERN.search(path.name) or CONTENT_MARKER in source:
            candidates.append(relative)
    return tuple(candidates)


def _text(value: object, field: str, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{path}: {field} must be a non-empty string")
    if value != value.strip():
        raise ManifestError(f"{path}: {field} must not contain surrounding whitespace")
    return value


def _entry(value: object, repository: Path, index: int) -> TestOwnership:
    label = f"tests[{index}]"
    if not isinstance(value, dict):
        raise ManifestError(f"{label}: entry must be an object")
    keys = frozenset(value)
    if keys != ENTRY_KEYS:
        missing = sorted(ENTRY_KEYS - keys)
        unknown = sorted(keys - ENTRY_KEYS)
        raise ManifestError(
            f"{label}: invalid fields; missing={missing}, unknown={unknown}"
        )

    path = _text(value["path"], "path", label)
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != path:
        raise ManifestError(
            f"{label}: path must be a normalized repository-relative POSIX path"
        )
    if (
        len(pure.parts) != 2
        or pure.parts[0] != "tests"
        or not pure.name.startswith("test_")
        or pure.suffix != ".py"
    ):
        raise ManifestError(f"{label}: path must name a top-level tests/test_*.py file")
    if not (repository / pure).is_file():
        raise ManifestError(f"{label}: stale path does not exist: {path}")

    tier = _text(value["tier"], "tier", path)
    if tier not in ALLOWED_TIERS:
        raise ManifestError(f"{path}: unknown tier: {tier}")
    owner = _text(value["owner"], "owner", path)
    reason = _text(value["reason"], "reason", path)
    required = value["required"]
    if not isinstance(required, bool):
        raise ManifestError(f"{path}: required must be boolean")

    group_value = value["group"]
    group: str | None
    if required:
        if tier != REQUIRED_TIER:
            raise ManifestError(
                f"{path}: required entries must use tier {REQUIRED_TIER}"
            )
        group = _text(group_value, "group", path)
        if group not in ALLOWED_GROUPS:
            raise ManifestError(f"{path}: unknown required group: {group}")
    else:
        if tier == REQUIRED_TIER:
            raise ManifestError(f"{path}: tier {REQUIRED_TIER} must set required=true")
        if group_value is not None:
            raise ManifestError(f"{path}: non-required entries must set group=null")
        group = None
        if tier == DELEGATED_TIER:
            _delegated_classifier_pattern(path, owner)
    return TestOwnership(path, tier, owner, required, reason, group)


def _delegated_classifier_pattern(path: str, owner: str) -> str:
    if owner == "c1" and path.startswith("tests/test_postgres_c1"):
        return "tests/test_postgres_c1*.py"
    if owner == "c2" and path.startswith("tests/test_postgres_c2"):
        return "tests/test_postgres_c2*.py"
    if owner == "c2" and path.startswith("tests/test_postgres_c3"):
        return "tests/test_postgres_c3*.py"
    if owner not in DELEGATED_WORKFLOWS:
        raise ManifestError(f"{path}: unknown delegated owner: {owner}")
    raise ManifestError(f"{path}: delegated path is not owned by {owner}")


def _pytest_targets(workflow: str) -> frozenset[str]:
    targets: set[str] = set()
    for match in PYTEST_COMMAND.finditer(workflow):
        try:
            arguments = shlex.split(match.group("arguments"), posix=True)
        except ValueError as error:
            raise ManifestError(
                f"cannot parse upstream pytest command: {error}"
            ) from error
        targets.update(
            argument for argument in arguments if argument.startswith("tests/")
        )
    return frozenset(targets)


def _validate_delegated_upstream(
    repository: Path, entries: tuple[TestOwnership, ...]
) -> None:
    delegated = tuple(entry for entry in entries if entry.tier == DELEGATED_TIER)
    for owner in sorted({entry.owner for entry in delegated}):
        workflow_path = repository / DELEGATED_WORKFLOWS[owner]
        try:
            workflow = workflow_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ManifestError(
                f"cannot read delegated owner workflow {workflow_path}: {error}"
            ) from error
        context = DELEGATED_CONTEXTS[owner]
        if f"name: {context}" not in workflow:
            raise ManifestError(f"delegated owner context is missing: {context}")
        targets = _pytest_targets(workflow)
        for entry in (item for item in delegated if item.owner == owner):
            if entry.path not in targets:
                raise ManifestError(
                    f"delegated test is not an upstream pytest target: {entry.path}"
                )
            classifier = _delegated_classifier_pattern(entry.path, owner)
            if classifier not in workflow:
                raise ManifestError(
                    f"delegated test is not covered by upstream classifier: {entry.path}"
                )


def validate_manifest(repository: Path, manifest_path: Path) -> ManifestInventory:
    repository = repository.resolve()
    document = _load_json(manifest_path)
    if not isinstance(document, dict) or frozenset(document) != {
        "schema_version",
        "tests",
    }:
        raise ManifestError("manifest must contain only schema_version and tests")
    if document["schema_version"] != 1:
        raise ManifestError("schema_version must be 1")
    values = document["tests"]
    if not isinstance(values, list) or not values:
        raise ManifestError("tests must be a non-empty list")

    entries = tuple(
        _entry(value, repository, index) for index, value in enumerate(values)
    )
    paths = [entry.path for entry in entries]
    duplicates = sorted({path for path in paths if paths.count(path) > 1})
    if duplicates:
        raise ManifestError(f"duplicate test entries: {duplicates}")
    if paths != sorted(paths):
        raise ManifestError("test entries must be sorted by path")

    candidates = discover_candidates(repository)
    manifest_paths = frozenset(paths)
    missing = sorted(set(candidates) - manifest_paths)
    if missing:
        raise ManifestError(f"unclassified Training candidates: {missing}")
    if not any(entry.required for entry in entries):
        raise ManifestError("required test set must not be empty")
    _validate_delegated_upstream(repository, entries)
    return ManifestInventory(entries, candidates)


def emit_required(
    inventory: ManifestInventory,
    group: str,
    output: BinaryIO,
) -> None:
    if group not in ALLOWED_GROUPS:
        raise ManifestError(f"unknown required group: {group}")
    paths = [entry.path for entry in inventory.required if entry.group == group]
    if not paths:
        raise ManifestError(f"required group is empty: {group}")
    output.writelines(path.encode("utf-8") + b"\0" for path in paths)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(".github/ci/training-test-manifest.json"),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("validate")
    emit = subcommands.add_parser("emit-required")
    emit.add_argument("--group", required=True)
    return parser


def run(
    arguments: argparse.Namespace,
    *,
    text_output: TextIO = sys.stdout,
    binary_output: BinaryIO | None = None,
) -> int:
    repository = arguments.repository.resolve()
    manifest_path = arguments.manifest
    if not manifest_path.is_absolute():
        manifest_path = repository / manifest_path
    inventory = validate_manifest(repository, manifest_path)
    if arguments.command == "emit-required":
        emit_required(inventory, arguments.group, binary_output or sys.stdout.buffer)
        return 0
    summary = {
        "candidate_count": len(inventory.candidates),
        "manifest_entries": len(inventory.entries),
        "non_required_entries": len(inventory.entries) - len(inventory.required),
        "required_entries": len(inventory.required),
        "status": "valid",
    }
    text_output.write(json.dumps(summary, sort_keys=True) + "\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(_parser().parse_args(argv))
    except ManifestError as error:
        print(f"training-test-manifest: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
