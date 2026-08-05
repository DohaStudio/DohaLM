"""Metadata-only, fail-closed static preflight for EOS-DIAG-R3.

The module may read explicitly allowlisted repository source files and query
filesystem metadata.  It never opens checkpoint, tokenizer, or prompt payloads,
creates output directories, scans processes, loads a model, or touches CUDA.
"""

from __future__ import annotations

import importlib.metadata
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from src.data.checksums import sha256_bytes

from .eos_diagnostic_artifacts import (
    EXACT_ARTIFACT_FILENAMES,
    diagnostic_fingerprint,
)
from .eos_diagnostic_identity import (
    BackendIdentity,
    CandidateBEvaluationBinding,
    CheckpointIdentity,
    DependencyIdentity,
    PromptSetIdentity,
    TokenizerIdentity,
    evaluate_eos_diag_1,
    evaluate_eos_diag_2,
)
from .eos_generation_matrix import GenerationMatrix

EOS_DIAG_R3_SCHEMA_VERSION = 3
PREFLIGHT_STATUSES = frozenset(
    {
        "passed",
        "passed_with_conditions",
        "blocked",
        "incomplete",
        "incompatible",
        "failed",
    }
)
ERROR_CODES = frozenset(
    {
        "EOS_DIAG_PREFLIGHT_INVALID",
        "EOS_DIAG_REPOSITORY_STATE_INVALID",
        "EOS_DIAG_SOURCE_COMMIT_MISMATCH",
        "EOS_DIAG_BACKEND_FINGERPRINT_INVALID",
        "EOS_DIAG_DEPENDENCY_SNAPSHOT_INVALID",
        "EOS_DIAG_INPUT_ROOT_INVALID",
        "EOS_DIAG_INPUT_NOT_READ_ONLY",
        "EOS_DIAG_OUTPUT_ROOT_INVALID",
        "EOS_DIAG_OUTPUT_CONFLICT",
        "EOS_DIAG_DISK_SPACE_INSUFFICIENT",
        "EOS_DIAG_PATH_LENGTH_EXCEEDED",
        "EOS_DIAG_LOCK_CONFLICT",
        "EOS_DIAG_PROCESS_CONFLICT",
        "EOS_DIAG_IDENTITY_INCOMPLETE",
        "EOS_DIAG_GATE_NOT_READY",
    }
)

_FP = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_LOGICAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
_RUN_ID = re.compile(r"(?:SYNTHETIC-)?DOHALM-CANDIDATE-B-EOS-DIAGNOSTIC-\d{8}-\d{4}\Z")
_MODULE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}\Z")
_ALLOWED_BACKEND_SUFFIXES = frozenset({".py", ".json", ".yaml", ".yml"})
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_PROHIBITED_ACTIONS = (
    "checkpoint_payload_read",
    "tokenizer_payload_read",
    "prompt_payload_read",
    "checkpoint_load",
    "gpu",
    "generation",
    "training",
    "approval_issue",
    "runtime_request_create",
    "output_create",
)


class EOSDiagnosticPreflightError(RuntimeError):
    """Fail-closed error exposing only a stable, non-sensitive code."""

    def __init__(self, code: str) -> None:
        if code not in ERROR_CODES:
            code = "EOS_DIAG_PREFLIGHT_INVALID"
        super().__init__(code)
        self.code = code


def _fail(code: str) -> None:
    raise EOSDiagnosticPreflightError(code)


def _text(value: object, *, logical: bool = False) -> str:
    pattern = _LOGICAL if logical else _MODULE_NAME
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail("EOS_DIAG_PREFLIGHT_INVALID")
    if logical and (value.startswith("/") or "\\" in value or ".." in value.split("/")):
        _fail("EOS_DIAG_PREFLIGHT_INVALID")
    return value


def _fingerprint(value: object) -> str:
    if type(value) is not str or _FP.fullmatch(value) is None:
        _fail("EOS_DIAG_PREFLIGHT_INVALID")
    return value


def _source_commit(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail("EOS_DIAG_PREFLIGHT_INVALID")
    return value


@dataclass(frozen=True)
class StaticPreflightRequest:
    schema_version: int
    diagnostic_run_id: str
    checkpoint_identity_fingerprint: str
    tokenizer_identity_fingerprint: str
    prompt_set_identity_fingerprint: str
    generation_matrix_fingerprint: str
    backend_identity_fingerprint: str
    dependency_identity_fingerprint: str
    source_commit: str
    expected_branch: str
    expected_remote: str
    checkpoint_root_logical_id: str
    tokenizer_root_logical_id: str
    prompt_root_logical_id: str
    output_root_logical_id: str
    staging_root_logical_id: str
    failure_root_logical_id: str
    expected_artifact_set_fingerprint: str
    minimum_free_disk_bytes: int
    maximum_path_length: int
    lock_identity: str
    request_fingerprint: str

    def as_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def create(cls, **values: object) -> StaticPreflightRequest:
        fields = tuple(
            name
            for name in cls.__dataclass_fields__
            if name not in {"schema_version", "request_fingerprint"}
        )
        if set(values) != set(fields):
            _fail("EOS_DIAG_PREFLIGHT_INVALID")
        if (
            type(values["diagnostic_run_id"]) is not str
            or _RUN_ID.fullmatch(values["diagnostic_run_id"]) is None
        ):
            _fail("EOS_DIAG_PREFLIGHT_INVALID")
        for field in (
            "checkpoint_identity_fingerprint",
            "tokenizer_identity_fingerprint",
            "prompt_set_identity_fingerprint",
            "generation_matrix_fingerprint",
            "backend_identity_fingerprint",
            "dependency_identity_fingerprint",
            "expected_artifact_set_fingerprint",
        ):
            _fingerprint(values[field])
        _source_commit(values["source_commit"])
        for field in (
            "expected_branch",
            "checkpoint_root_logical_id",
            "tokenizer_root_logical_id",
            "prompt_root_logical_id",
            "output_root_logical_id",
            "staging_root_logical_id",
            "failure_root_logical_id",
            "lock_identity",
        ):
            _text(values[field], logical=True)
        remote = values["expected_remote"]
        if remote != "https://github.com/DohaStudio/DohaLM.git":
            _fail("EOS_DIAG_PREFLIGHT_INVALID")
        for field in ("minimum_free_disk_bytes", "maximum_path_length"):
            if type(values[field]) is not int or values[field] <= 0:
                _fail("EOS_DIAG_PREFLIGHT_INVALID")
        semantic = {"schema_version": EOS_DIAG_R3_SCHEMA_VERSION, **values}
        return cls(
            **semantic,
            request_fingerprint=diagnostic_fingerprint(semantic),
        )  # type: ignore[arg-type]

    @classmethod
    def from_mapping(cls, value: object) -> StaticPreflightRequest:
        if type(value) is not dict or set(value) != set(cls.__dataclass_fields__):
            _fail("EOS_DIAG_PREFLIGHT_INVALID")
        if value["schema_version"] != EOS_DIAG_R3_SCHEMA_VERSION:
            _fail("EOS_DIAG_PREFLIGHT_INVALID")
        result = cls.create(
            **{
                key: item
                for key, item in value.items()
                if key not in {"schema_version", "request_fingerprint"}
            }
        )
        if value["request_fingerprint"] != result.request_fingerprint:
            _fail("EOS_DIAG_PREFLIGHT_INVALID")
        return result


@dataclass(frozen=True)
class GitCommandResult:
    returncode: int
    stdout: str = ""


GitRunner = Callable[[Path, tuple[str, ...]], GitCommandResult]


@dataclass(frozen=True)
class RepositoryState:
    branch: str
    remote_identity: str
    head: str
    origin_develop: str
    worktree_clean: bool
    detached_head: bool
    operation_in_progress: bool
    status: str

    def as_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _git_runner(root: Path, arguments: tuple[str, ...]) -> GitCommandResult:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        _fail("EOS_DIAG_REPOSITORY_STATE_INVALID")
    return GitCommandResult(completed.returncode, completed.stdout.strip())


def validate_repository_state(
    repository_root: Path,
    request: StaticPreflightRequest,
    *,
    command_runner: GitRunner = _git_runner,
) -> RepositoryState:
    """Validate only the explicit repository; never discover another checkout."""
    if not isinstance(repository_root, Path):
        _fail("EOS_DIAG_REPOSITORY_STATE_INVALID")
    try:
        if repository_root.is_symlink() or not repository_root.is_dir():
            _fail("EOS_DIAG_REPOSITORY_STATE_INVALID")
        root = repository_root.resolve(strict=True)
    except (OSError, RuntimeError):
        _fail("EOS_DIAG_REPOSITORY_STATE_INVALID")

    def git(*arguments: str) -> str:
        result = command_runner(root, tuple(arguments))
        if result.returncode != 0:
            _fail("EOS_DIAG_REPOSITORY_STATE_INVALID")
        return result.stdout.strip()

    branch = git("branch", "--show-current")
    head = git("rev-parse", "HEAD")
    origin = git("rev-parse", "origin/develop")
    remote = git("remote", "get-url", "origin")
    status = git("status", "--porcelain=v1", "--untracked-files=all")
    git_dir = git("rev-parse", "--git-dir")
    detached = not branch
    operation_markers = (
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REBASE_HEAD",
        "rebase-merge",
        "rebase-apply",
    )
    operation = False
    git_path = root / git_dir
    try:
        operation = any((git_path / marker).exists() for marker in operation_markers)
    except OSError:
        _fail("EOS_DIAG_REPOSITORY_STATE_INVALID")
    if head != request.source_commit or origin != request.source_commit:
        _fail("EOS_DIAG_SOURCE_COMMIT_MISMATCH")
    if (
        detached
        or branch != request.expected_branch
        or remote != request.expected_remote
        or status
        or operation
    ):
        _fail("EOS_DIAG_REPOSITORY_STATE_INVALID")
    return RepositoryState(
        branch, "DohaStudio/DohaLM", head, origin, True, False, False, "passed"
    )


@dataclass(frozen=True)
class BackendModuleSpec:
    logical_name: str
    relative_path: str


def build_backend_identity(
    repository_root: Path,
    *,
    source_commit: str,
    modules: Sequence[BackendModuleSpec],
    backend_name: str = "dohalm-eos-diagnostic-backend",
    backend_version: str = "r3",
) -> BackendIdentity:
    """Hash only caller-allowlisted source/schema files with mutation detection."""
    _source_commit(source_commit)
    if not modules:
        _fail("EOS_DIAG_BACKEND_FINGERPRINT_INVALID")
    try:
        root = repository_root.resolve(strict=True)
    except (OSError, RuntimeError):
        _fail("EOS_DIAG_BACKEND_FINGERPRINT_INVALID")
    names = [item.logical_name for item in modules]
    paths = [item.relative_path for item in modules]
    if len(names) != len(set(names)) or len(paths) != len(set(paths)):
        _fail("EOS_DIAG_BACKEND_FINGERPRINT_INVALID")
    fingerprints: dict[str, str] = {}
    for spec in sorted(
        modules, key=lambda item: (item.logical_name, item.relative_path)
    ):
        _text(spec.logical_name)
        relative = Path(spec.relative_path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.suffix.lower() not in _ALLOWED_BACKEND_SUFFIXES
        ):
            _fail("EOS_DIAG_BACKEND_FINGERPRINT_INVALID")
        path = root / relative
        try:
            if (
                path.is_symlink()
                or not path.is_file()
                or path.resolve(strict=True).parent
                != (root / relative.parent).resolve(strict=True)
            ):
                _fail("EOS_DIAG_BACKEND_FINGERPRINT_INVALID")
            if not path.resolve(strict=True).is_relative_to(root):
                _fail("EOS_DIAG_BACKEND_FINGERPRINT_INVALID")
            before = path.stat()
            payload = path.read_bytes()
            after = path.stat()
        except (OSError, RuntimeError):
            _fail("EOS_DIAG_BACKEND_FINGERPRINT_INVALID")
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            _fail("EOS_DIAG_BACKEND_FINGERPRINT_INVALID")
        fingerprints[spec.logical_name] = sha256_bytes(payload)
    return BackendIdentity.create(
        backend_name=backend_name,
        backend_version=backend_version,
        source_commit=source_commit,
        module_fingerprints=fingerprints,
        config_schema_version="2",
        artifact_schema_version="1",
    )


@dataclass(frozen=True)
class DependencyRequirement:
    name: str
    required: bool = True


VersionProvider = Callable[[str], str]


def _installed_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "missing"


def build_dependency_identity(
    requirements: Sequence[DependencyRequirement],
    *,
    python_version: str,
    platform_identity: str,
    torch_version: str,
    cuda_build: str,
    cudnn_version: str,
    version_provider: VersionProvider = _installed_version,
) -> DependencyIdentity:
    """Build a path-free snapshot from an explicit dependency allowlist."""
    if not requirements:
        _fail("EOS_DIAG_DEPENDENCY_SNAPSHOT_INVALID")
    names = [item.name for item in requirements]
    if len(names) != len(set(names)):
        _fail("EOS_DIAG_DEPENDENCY_SNAPSHOT_INVALID")
    entries: list[dict[str, object]] = []
    for requirement in sorted(requirements, key=lambda item: item.name):
        _text(requirement.name)
        version = version_provider(requirement.name)
        if type(version) is not str or (
            version != "missing" and _VERSION.fullmatch(version) is None
        ):
            _fail("EOS_DIAG_DEPENDENCY_SNAPSHOT_INVALID")
        if requirement.required and version == "missing":
            _fail("EOS_DIAG_DEPENDENCY_SNAPSHOT_INVALID")
        entries.append(
            {
                "name": requirement.name,
                "version": version,
                "required": requirement.required,
                "source": "installed-metadata",
            }
        )
    for value in (
        python_version,
        platform_identity,
        torch_version,
        cuda_build,
        cudnn_version,
    ):
        if type(value) is not str or _VERSION.fullmatch(value) is None:
            _fail("EOS_DIAG_DEPENDENCY_SNAPSHOT_INVALID")
    return DependencyIdentity.create(
        python_version=python_version,
        torch_version=torch_version,
        cuda_build=cuda_build,
        cudnn_version=cudnn_version,
        platform=platform_identity,
        dependency_entries=entries,
    )


def snapshot_current_dependencies(
    requirements: Sequence[DependencyRequirement],
) -> DependencyIdentity:
    """Query versions only; importing torch does not initialize or inspect CUDA devices."""
    try:
        import torch

        torch_version = str(torch.__version__)
        cuda_build = str(torch.version.cuda or "none")
        cudnn_version = str(torch.backends.cudnn.version() or "none")
    except (ImportError, AttributeError, RuntimeError):
        _fail("EOS_DIAG_DEPENDENCY_SNAPSHOT_INVALID")
    return build_dependency_identity(
        requirements,
        python_version=platform.python_version(),
        platform_identity=f"{sys.platform}-{platform.machine()}",
        torch_version=torch_version,
        cuda_build=cuda_build,
        cudnn_version=cudnn_version,
    )


@dataclass(frozen=True)
class InputRootSpec:
    kind: str
    logical_id: str
    path: Path
    expected_metadata_name: str


@dataclass(frozen=True)
class InputRootStatus:
    kind: str
    logical_id: str
    status: str
    metadata_exists: bool
    symlink_free: bool
    readable_by_metadata_check: bool
    payload_reads: int
    write_attempts: int

    def as_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def validate_input_roots(specs: Sequence[InputRootSpec]) -> tuple[InputRootStatus, ...]:
    """Use stat/access only; expected metadata files are never opened or parsed."""
    if tuple(item.kind for item in specs) != ("checkpoint", "tokenizer", "prompt"):
        _fail("EOS_DIAG_INPUT_ROOT_INVALID")
    resolved: list[Path] = []
    statuses: list[InputRootStatus] = []
    for spec in specs:
        _text(spec.logical_id, logical=True)
        if Path(spec.expected_metadata_name).name != spec.expected_metadata_name:
            _fail("EOS_DIAG_INPUT_ROOT_INVALID")
        try:
            if spec.path.is_symlink() or not spec.path.is_dir():
                _fail("EOS_DIAG_INPUT_ROOT_INVALID")
            root = spec.path.resolve(strict=True)
            metadata = root / spec.expected_metadata_name
            if metadata.is_symlink() or not metadata.is_file():
                _fail("EOS_DIAG_INPUT_ROOT_INVALID")
            metadata.stat()
            if not os.access(root, os.R_OK) or not os.access(metadata, os.R_OK):
                _fail("EOS_DIAG_INPUT_NOT_READ_ONLY")
        except EOSDiagnosticPreflightError:
            raise
        except (OSError, RuntimeError):
            _fail("EOS_DIAG_INPUT_ROOT_INVALID")
        if any(
            root == other or root.is_relative_to(other) or other.is_relative_to(root)
            for other in resolved
        ):
            _fail("EOS_DIAG_INPUT_ROOT_INVALID")
        resolved.append(root)
        statuses.append(
            InputRootStatus(
                spec.kind, spec.logical_id, "passed", True, True, True, 0, 0
            )
        )
    return tuple(statuses)


@dataclass(frozen=True)
class LocalPreflightPaths:
    repository_root: Path
    checkpoint_root: Path
    tokenizer_root: Path
    prompt_root: Path
    output_root: Path
    staging_root: Path
    failure_root: Path
    lock_path: Path


@dataclass(frozen=True)
class OutputDestinationStatus:
    status: str
    output_root_logical_id: str
    staging_root_logical_id: str
    failure_root_logical_id: str
    destinations_new: bool
    parents_writable_by_metadata_check: bool
    same_volume: bool
    available_bytes: int
    required_bytes: int
    longest_projected_path: int
    maximum_path_length: int
    lock_clear: bool
    process_clear: bool

    def as_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


DiskUsageProvider = Callable[[Path], Any]


def validate_output_destinations(
    paths: LocalPreflightPaths,
    request: StaticPreflightRequest,
    *,
    process_run_ids: Sequence[str],
    disk_usage_provider: DiskUsageProvider = shutil.disk_usage,
) -> OutputDestinationStatus:
    destinations = (paths.output_root, paths.staging_root, paths.failure_root)
    if len(set(destinations)) != 3 or len(process_run_ids) != len(set(process_run_ids)):
        _fail("EOS_DIAG_OUTPUT_CONFLICT")
    if request.diagnostic_run_id in process_run_ids:
        _fail("EOS_DIAG_PROCESS_CONFLICT")
    if paths.lock_path.exists() or paths.lock_path.is_symlink():
        _fail("EOS_DIAG_LOCK_CONFLICT")
    try:
        repository = paths.repository_root.resolve(strict=True)
        inputs = tuple(
            item.resolve(strict=True)
            for item in (paths.checkpoint_root, paths.tokenizer_root, paths.prompt_root)
        )
        parents: list[Path] = []
        for destination in destinations:
            if (
                destination.name.split(".", maxsplit=1)[0].upper()
                in _WINDOWS_RESERVED_NAMES
            ):
                _fail("EOS_DIAG_OUTPUT_CONFLICT")
            if (
                destination.exists()
                or destination.is_symlink()
                or destination.with_name(destination.name + ".tmp").exists()
            ):
                _fail("EOS_DIAG_OUTPUT_CONFLICT")
            parent = destination.parent
            if (
                parent.is_symlink()
                or not parent.is_dir()
                or not os.access(parent, os.W_OK)
            ):
                _fail("EOS_DIAG_OUTPUT_ROOT_INVALID")
            resolved_parent = parent.resolve(strict=True)
            projected = resolved_parent / destination.name
            if projected.is_relative_to(repository) or any(
                projected.is_relative_to(root) for root in inputs
            ):
                _fail("EOS_DIAG_OUTPUT_ROOT_INVALID")
            parents.append(resolved_parent)
        devices = {parent.stat().st_dev for parent in parents}
    except EOSDiagnosticPreflightError:
        raise
    except (OSError, RuntimeError):
        _fail("EOS_DIAG_OUTPUT_ROOT_INVALID")
    if len(devices) != 1:
        _fail("EOS_DIAG_OUTPUT_ROOT_INVALID")
    longest_name = max(EXACT_ARTIFACT_FILENAMES, key=len)
    suffixes = ("", ".tmp", ".failed")
    longest = max(
        len(str(destination / longest_name)) + len(suffix)
        for destination in destinations
        for suffix in suffixes
    )
    if longest > request.maximum_path_length:
        _fail("EOS_DIAG_PATH_LENGTH_EXCEEDED")
    try:
        available = int(disk_usage_provider(parents[0]).free)
    except (OSError, AttributeError, TypeError, ValueError):
        _fail("EOS_DIAG_OUTPUT_ROOT_INVALID")
    if available < request.minimum_free_disk_bytes:
        _fail("EOS_DIAG_DISK_SPACE_INSUFFICIENT")
    return OutputDestinationStatus(
        "passed",
        request.output_root_logical_id,
        request.staging_root_logical_id,
        request.failure_root_logical_id,
        True,
        True,
        True,
        available,
        request.minimum_free_disk_bytes,
        longest,
        request.maximum_path_length,
        True,
        True,
    )


@dataclass(frozen=True)
class IdentityBlocker:
    blocker_id: str
    severity: str
    status: str
    source: str
    resolution: str
    blocking_gate: str

    def as_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def map_identity_blockers(
    checkpoint: CheckpointIdentity,
    prompt: PromptSetIdentity,
    backend: BackendIdentity,
    dependency: DependencyIdentity,
    *,
    source_commit: str | None,
) -> tuple[IdentityBlocker, ...]:
    definitions = (
        (
            checkpoint.checkpoint_manifest_fingerprint,
            "checkpoint_manifest_fingerprint",
            "critical",
            "checkpoint_identity",
            "freeze independent checkpoint manifest fingerprint",
            "EOS-DIAG-1",
        ),
        (
            prompt.prompt_set_id,
            "prompt_set_id",
            "critical",
            "prompt_identity",
            "freeze formal prompt set ID",
            "EOS-DIAG-1",
        ),
        (
            prompt.prompt_set_version,
            "prompt_set_version",
            "critical",
            "prompt_identity",
            "freeze formal prompt set version",
            "EOS-DIAG-1",
        ),
        (
            prompt.token_length_distribution,
            "token_length_distribution",
            "high",
            "prompt_identity",
            "freeze token-length distribution",
            "EOS-DIAG-1",
        ),
        (
            prompt.normalization_policy,
            "normalization_evidence",
            "high",
            "prompt_identity",
            "freeze prompt normalization evidence",
            "EOS-DIAG-1",
        ),
        (
            prompt.leakage_status,
            "leakage_evidence",
            "critical",
            "prompt_identity",
            "freeze formal leakage evidence",
            "EOS-DIAG-1",
        ),
        (
            source_commit,
            "source_commit",
            "critical",
            "repository",
            "freeze diagnostic source commit",
            "EOS-DIAG-1",
        ),
        (
            backend.module_fingerprints,
            "backend_module_fingerprint",
            "critical",
            "backend_identity",
            "supply explicit allowlist module fingerprint",
            "EOS-DIAG-2",
        ),
        (
            dependency.dependency_entries,
            "dependency_snapshot_fingerprint",
            "critical",
            "dependency_identity",
            "supply exact dependency snapshot",
            "EOS-DIAG-2",
        ),
    )
    return tuple(
        IdentityBlocker(
            f"EOS-DIAG-R3-{index:03d}", severity, "blocked", source, resolution, gate
        )
        for index, (value, _name, severity, source, resolution, gate) in enumerate(
            definitions, 1
        )
        if value is None
    )


@dataclass(frozen=True)
class StaticPreflightResult:
    schema_version: int
    diagnostic_run_id: str
    status: str
    request_fingerprint: str
    repository_state: Mapping[str, object]
    backend_fingerprint: str
    dependency_fingerprint: str
    input_root_status: tuple[Mapping[str, object], ...]
    output_destination_status: Mapping[str, object]
    gate_1_status: str
    gate_2_status: str
    blockers: tuple[Mapping[str, str], ...]
    approved_next_actions: tuple[str, ...]
    prohibited_actions: tuple[str, ...]
    diagnostic_execution_allowed: bool
    preflight_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "repository_state", MappingProxyType(dict(self.repository_state))
        )
        object.__setattr__(
            self,
            "input_root_status",
            tuple(MappingProxyType(dict(item)) for item in self.input_root_status),
        )
        object.__setattr__(
            self,
            "output_destination_status",
            MappingProxyType(dict(self.output_destination_status)),
        )
        object.__setattr__(
            self,
            "blockers",
            tuple(MappingProxyType(dict(item)) for item in self.blockers),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "diagnostic_run_id": self.diagnostic_run_id,
            "status": self.status,
            "request_fingerprint": self.request_fingerprint,
            "repository_state": dict(self.repository_state),
            "backend_fingerprint": self.backend_fingerprint,
            "dependency_fingerprint": self.dependency_fingerprint,
            "input_root_status": [dict(item) for item in self.input_root_status],
            "output_destination_status": dict(self.output_destination_status),
            "gate_1_status": self.gate_1_status,
            "gate_2_status": self.gate_2_status,
            "blockers": [dict(item) for item in self.blockers],
            "approved_next_actions": list(self.approved_next_actions),
            "prohibited_actions": list(self.prohibited_actions),
            "diagnostic_execution_allowed": self.diagnostic_execution_allowed,
            "preflight_fingerprint": self.preflight_fingerprint,
        }


def run_static_preflight(
    request: StaticPreflightRequest,
    *,
    paths: LocalPreflightPaths,
    repository_state: RepositoryState,
    backend: BackendIdentity,
    dependency: DependencyIdentity,
    checkpoint: CheckpointIdentity,
    tokenizer: TokenizerIdentity,
    prompt_set: PromptSetIdentity,
    binding: CandidateBEvaluationBinding,
    matrix: GenerationMatrix,
    input_statuses: Sequence[InputRootStatus],
    output_status: OutputDestinationStatus,
) -> StaticPreflightResult:
    """Map already validated metadata to Gate 1/2 without granting execution."""
    request = StaticPreflightRequest.from_mapping(request.as_dict())
    expected_inputs = (
        ("checkpoint", request.checkpoint_root_logical_id),
        ("tokenizer", request.tokenizer_root_logical_id),
        ("prompt", request.prompt_root_logical_id),
    )
    expected_outputs = (
        request.output_root_logical_id,
        request.staging_root_logical_id,
        request.failure_root_logical_id,
    )
    if (
        repository_state.status != "passed"
        or repository_state.branch != request.expected_branch
        or repository_state.remote_identity != "DohaStudio/DohaLM"
        or repository_state.head != request.source_commit
        or repository_state.origin_develop != request.source_commit
        or not repository_state.worktree_clean
        or repository_state.detached_head
        or repository_state.operation_in_progress
        or backend.backend_fingerprint != request.backend_identity_fingerprint
        or dependency.dependency_fingerprint != request.dependency_identity_fingerprint
        or checkpoint.identity_fingerprint != request.checkpoint_identity_fingerprint
        or tokenizer.identity_fingerprint != request.tokenizer_identity_fingerprint
        or prompt_set.identity_fingerprint != request.prompt_set_identity_fingerprint
        or matrix.matrix_fingerprint != request.generation_matrix_fingerprint
        or request.expected_artifact_set_fingerprint
        != diagnostic_fingerprint(list(EXACT_ARTIFACT_FILENAMES))
        or output_status.status != "passed"
        or (
            output_status.output_root_logical_id,
            output_status.staging_root_logical_id,
            output_status.failure_root_logical_id,
        )
        != expected_outputs
        or tuple((item.kind, item.logical_id) for item in input_statuses)
        != expected_inputs
        or any(item.status != "passed" for item in input_statuses)
    ):
        _fail("EOS_DIAG_PREFLIGHT_INVALID")
    gate_1 = evaluate_eos_diag_1(checkpoint, tokenizer, prompt_set, binding)
    gate_2 = evaluate_eos_diag_2(
        matrix,
        backend,
        dependency,
        artifact_set=EXACT_ARTIFACT_FILENAMES,
        source_commit=request.source_commit,
    )
    blockers = map_identity_blockers(
        checkpoint, prompt_set, backend, dependency, source_commit=request.source_commit
    )
    status = (
        "passed"
        if gate_1.status == gate_2.status == "passed" and not blockers
        else "blocked"
    )
    semantic: dict[str, object] = {
        "schema_version": EOS_DIAG_R3_SCHEMA_VERSION,
        "diagnostic_run_id": request.diagnostic_run_id,
        "status": status,
        "request_fingerprint": request.request_fingerprint,
        "repository_state": repository_state.as_dict(),
        "backend_fingerprint": backend.backend_fingerprint,
        "dependency_fingerprint": dependency.dependency_fingerprint,
        "input_root_status": [item.as_dict() for item in input_statuses],
        "output_destination_status": output_status.as_dict(),
        "gate_1_status": gate_1.status,
        "gate_2_status": gate_2.status,
        "blockers": [item.as_dict() for item in blockers],
        "approved_next_actions": ["review_preflight_evidence"],
        "prohibited_actions": list(_PROHIBITED_ACTIONS),
        "diagnostic_execution_allowed": False,
    }
    result = StaticPreflightResult(
        schema_version=EOS_DIAG_R3_SCHEMA_VERSION,
        diagnostic_run_id=request.diagnostic_run_id,
        status=status,
        request_fingerprint=request.request_fingerprint,
        repository_state=repository_state.as_dict(),
        backend_fingerprint=backend.backend_fingerprint,
        dependency_fingerprint=dependency.dependency_fingerprint,
        input_root_status=tuple(item.as_dict() for item in input_statuses),
        output_destination_status=output_status.as_dict(),
        gate_1_status=gate_1.status,
        gate_2_status=gate_2.status,
        blockers=tuple(item.as_dict() for item in blockers),
        approved_next_actions=("review_preflight_evidence",),
        prohibited_actions=_PROHIBITED_ACTIONS,
        diagnostic_execution_allowed=False,
        preflight_fingerprint=diagnostic_fingerprint(semantic),
    )
    if result.status not in PREFLIGHT_STATUSES or result.diagnostic_execution_allowed:
        _fail("EOS_DIAG_GATE_NOT_READY")
    return result


def build_diagnostic_plan_preflight_section(
    result: StaticPreflightResult,
) -> dict[str, object]:
    """Return the R1 diagnostic-plan preflight section; no artifact is written."""
    value = result.as_dict()
    if value["diagnostic_execution_allowed"] is not False:
        _fail("EOS_DIAG_GATE_NOT_READY")
    return value
