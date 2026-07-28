"""Fail-closed mapping contract for the external AIHUB-71748 package."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping


DATASET_ID = "AIHUB-71748"
COMPONENT = "SFT"
LOGICAL_ROOT = "${DOHALM_DATASET_ROOT}/AIHUB-71748"
LOGICAL_PROCESSED_ROOT = "${DOHALM_DATASET_ROOT}/processed/instruct/AIHUB-71748"
ALLOWED_COMPONENTS = ("SFTdata", "SFTlabel")
ALLOWED_SPLITS = ("Training", "Validation")


class DatasetMappingError(RuntimeError):
    """Mapping failure carrying no local path in its message."""


@dataclass(frozen=True)
class ResolvedDatasetMapping:
    dataset_id: str
    component: str
    source_root: Path
    processed_root: Path
    resolution_source: str
    read_only: bool = True
    execution_allowed: bool = False


def canonical_mapping_contract() -> dict[str, object]:
    return {
        "dataset_id": DATASET_ID,
        "component": COMPONENT,
        "root": LOGICAL_ROOT,
        "root_type": "external",
        "repository_internal": False,
        "read_only": True,
        "provider": "AI_Hub",
        "allowed_components": list(ALLOWED_COMPONENTS),
        "allowed_splits": list(ALLOWED_SPLITS),
        "raw_immutable": True,
        "processed_root": LOGICAL_PROCESSED_ROOT,
    }


def validate_mapping_contract(mapping: Mapping[str, object]) -> None:
    if not isinstance(mapping, Mapping):
        raise DatasetMappingError("DATASET_MAPPING_MISSING")
    if set(mapping) != set(canonical_mapping_contract()):
        raise DatasetMappingError("DATASET_MAPPING_INVALID")
    expected = canonical_mapping_contract()
    for key, value in expected.items():
        candidate = mapping.get(key)
        if key in {"allowed_components", "allowed_splits"}:
            if not isinstance(candidate, (list, tuple)) or tuple(candidate) != tuple(value):
                raise DatasetMappingError("DATASET_COMPONENT_MISMATCH")
        elif candidate != value:
            code = {
                "root_type": "DATASET_ROOT_TYPE_INVALID",
                "repository_internal": "REPOSITORY_INTERNAL_FLAG_INVALID",
                "read_only": "SOURCE_NOT_READ_ONLY",
                "component": "DATASET_COMPONENT_MISMATCH",
            }.get(key, "DATASET_MAPPING_INVALID")
            raise DatasetMappingError(code)


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _redirected(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if not candidate.is_dir() or _redirected(candidate):
        raise DatasetMappingError("DATASET_MAPPING_INVALID")
    return candidate


def _resolve_local_entry(local_config: Mapping[str, object]) -> tuple[Path, Path] | None:
    datasets = local_config.get("datasets")
    if not isinstance(datasets, Mapping):
        raise DatasetMappingError("DATASET_MAPPING_INVALID")
    external_root = datasets.get("external_root")
    entries = datasets.get("entries")
    if not isinstance(entries, Mapping) or DATASET_ID not in entries:
        return None
    entry = entries[DATASET_ID]
    if not isinstance(external_root, str) or not isinstance(entry, Mapping):
        raise DatasetMappingError("DATASET_MAPPING_INVALID")
    required = {
        "dataset_id": DATASET_ID,
        "component": COMPONENT,
        "root_type": "external",
        "repository_internal": False,
        "read_only": True,
        "raw_immutable": True,
    }
    if any(entry.get(key) != value for key, value in required.items()):
        raise DatasetMappingError("DATASET_MAPPING_INVALID")
    root = entry.get("root")
    processed = entry.get("processed_root", "processed/instruct/AIHUB-71748")
    if not isinstance(root, str) or not isinstance(processed, str):
        raise DatasetMappingError("DATASET_MAPPING_INVALID")
    base = Path(external_root).expanduser().resolve()
    raw_source = base / root if not Path(root).is_absolute() else Path(root)
    if _redirected(raw_source):
        raise DatasetMappingError("DATASET_MAPPING_INVALID")
    source = raw_source.resolve()
    output = (base / processed).resolve() if not Path(processed).is_absolute() else Path(processed).resolve()
    return source, output


def resolve_dataset_mapping(
    *,
    repository_root: str | Path,
    explicit_root: str | Path | None = None,
    local_config: Mapping[str, object] | None = None,
    environment: Mapping[str, str] | None = None,
) -> ResolvedDatasetMapping:
    """Resolve CLI, local config, then environment without guessing a fallback."""

    repository = Path(repository_root).resolve()
    source: Path | None = None
    output: Path | None = None
    resolution_source = ""
    if explicit_root is not None:
        raw_source = Path(explicit_root).expanduser()
        if _redirected(raw_source):
            raise DatasetMappingError("DATASET_MAPPING_INVALID")
        source = raw_source.resolve()
        base = source.parent.parent if source.parent.name.casefold() == "extracted" else source.parent
        output = (base / "processed" / "instruct" / DATASET_ID).resolve()
        resolution_source = "explicit_cli"
    elif local_config is not None:
        resolved = _resolve_local_entry(local_config)
        if resolved is not None:
            source, output = resolved
            resolution_source = "local_config"
    if source is None:
        env = os.environ if environment is None else environment
        value = env.get("DOHALM_DATASET_ROOT")
        if value:
            base = Path(value).expanduser().resolve()
            candidates = (base / DATASET_ID, base / "extracted" / DATASET_ID)
            existing = [candidate for candidate in candidates if candidate.is_dir()]
            if len(existing) != 1:
                raise DatasetMappingError("DATASET_ROOT_UNRESOLVED")
            if _redirected(existing[0]):
                raise DatasetMappingError("DATASET_MAPPING_INVALID")
            source = existing[0].resolve()
            output = (base / "processed" / "instruct" / DATASET_ID).resolve()
            resolution_source = "environment"
    if source is None or output is None:
        raise DatasetMappingError("DATASET_ROOT_UNRESOLVED")
    if not source.is_absolute() or not output.is_absolute():
        raise DatasetMappingError("DATASET_ROOT_UNRESOLVED")
    if not source.is_dir():
        raise DatasetMappingError("DATASET_ROOT_NOT_FOUND")
    if source.name.casefold() != DATASET_ID.casefold():
        raise DatasetMappingError("DATASET_MAPPING_INVALID")
    if _inside(source, repository):
        raise DatasetMappingError("DATASET_ROOT_INSIDE_REPOSITORY")
    if source == output or _inside(output, source) or _inside(source, output):
        raise DatasetMappingError("RAW_PROCESSED_PATH_COLLISION")
    if not os.access(existing_parent(output), os.W_OK):
        raise DatasetMappingError("DATASET_MAPPING_INVALID")
    return ResolvedDatasetMapping(
        dataset_id=DATASET_ID,
        component=COMPONENT,
        source_root=source,
        processed_root=output,
        resolution_source=resolution_source,
    )
