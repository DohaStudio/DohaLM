"""Explicit-input identity and freeze gates for EOS-DIAG-R2.

No function in this module discovers files, reads model/tokenizer/prompt
payloads, inspects the process environment, or grants execution permission.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .eos_diagnostic_artifacts import (
    EXACT_ARTIFACT_FILENAMES,
    DiagnosticArtifact,
    diagnostic_fingerprint,
    new_diagnostic_artifact,
)
from .eos_generation_matrix import GenerationMatrix

EOS_DIAG_R2_SCHEMA_VERSION = 2
FREEZE_STATUSES = frozenset(
    {"frozen", "frozen_with_limitations", "incomplete", "incompatible", "blocked"}
)
GATE_STATUSES = frozenset({"passed", "review", "blocked", "incomplete"})

_FP = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}\Z")


class EOSDiagnosticIdentityError(RuntimeError):
    """Fail-closed error exposing only a stable, non-sensitive code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fail(code: str) -> None:
    raise EOSDiagnosticIdentityError(code)


def _mapping(value: object, fields: Sequence[str], code: str) -> Mapping[str, Any]:
    if type(value) is not dict or set(value) != set(fields):
        _fail(code)
    return value


def _text(
    value: object, code: str, *, optional: bool = False, version: bool = False
) -> str | None:
    if value is None and optional:
        return None
    pattern = _VERSION if version else _ID
    if (
        type(value) is not str
        or pattern.fullmatch(value) is None
        or re.match(r"[A-Za-z]:/", value) is not None
        or ".." in value.split("/")
    ):
        _fail(code)
    return value


def _fp(value: object, code: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or _FP.fullmatch(value) is None:
        _fail(code)
    return value


def _sha(value: object, code: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail(code)
    return value


def _count_pairs(value: object, code: str) -> tuple[tuple[str, int], ...] | None:
    if value is None:
        return None
    if type(value) is dict:
        items = tuple(sorted(value.items()))
    elif type(value) in {list, tuple}:
        items = tuple(value)
    else:
        _fail(code)
    if not items or any(
        type(item) not in {tuple, list}
        or len(item) != 2
        or _ID.fullmatch(item[0]) is None
        or type(item[1]) is not int
        or item[1] < 0
        for item in items
    ):
        _fail(code)
    keys = tuple(item[0] for item in items)
    if len(keys) != len(set(keys)):
        _fail(code)
    return tuple((key, count) for key, count in items)


def _identity_fingerprint(value: Mapping[str, object]) -> str:
    return diagnostic_fingerprint(value)


@dataclass(frozen=True)
class CheckpointIdentity:
    schema_version: int
    checkpoint_id: str | None
    checkpoint_step: int | None
    checkpoint_checksum: str | None
    checkpoint_manifest_fingerprint: str | None
    model_config_fingerprint: str | None
    training_run_id: str | None
    training_source_commit: str | None
    evaluation_id: str | None
    evaluation_fingerprint: str | None
    architecture_id: str | None
    parameter_count: int | None
    dtype_contract: str | None
    immutable: bool
    identity_fingerprint: str

    def as_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}

    @classmethod
    def create(cls, **values: object) -> CheckpointIdentity:
        code = "EOS_DIAG_CHECKPOINT_IDENTITY_INVALID"
        expected = tuple(
            name
            for name in cls.__dataclass_fields__
            if name not in {"schema_version", "identity_fingerprint"}
        )
        mapping = _mapping(values, expected, code)
        for field in (
            "checkpoint_id",
            "training_run_id",
            "evaluation_id",
            "architecture_id",
            "dtype_contract",
        ):
            _text(mapping[field], code, optional=True)
        for field in (
            "checkpoint_checksum",
            "checkpoint_manifest_fingerprint",
            "model_config_fingerprint",
            "evaluation_fingerprint",
        ):
            _fp(mapping[field], code, optional=True)
        _sha(mapping["training_source_commit"], code, optional=True)
        for field in ("checkpoint_step", "parameter_count"):
            if mapping[field] is not None and (
                type(mapping[field]) is not int or mapping[field] <= 0
            ):
                _fail(code)
        if type(mapping["immutable"]) is not bool:
            _fail(code)
        semantic = {"schema_version": EOS_DIAG_R2_SCHEMA_VERSION, **mapping}
        return cls(**semantic, identity_fingerprint=_identity_fingerprint(semantic))  # type: ignore[arg-type]

    @classmethod
    def from_mapping(cls, value: object) -> CheckpointIdentity:
        code = "EOS_DIAG_CHECKPOINT_IDENTITY_INVALID"
        mapping = _mapping(value, cls.__dataclass_fields__, code)
        if mapping["schema_version"] != EOS_DIAG_R2_SCHEMA_VERSION:
            _fail(code)
        identity = cls.create(
            **{
                key: mapping[key]
                for key in mapping
                if key not in {"schema_version", "identity_fingerprint"}
            }
        )
        if _fp(mapping["identity_fingerprint"], code) != identity.identity_fingerprint:
            _fail(code)
        return identity


@dataclass(frozen=True)
class TokenizerIdentity:
    schema_version: int
    tokenizer_id: str | None
    tokenizer_version: str | None
    tokenizer_fingerprint: str | None
    tokenizer_manifest_checksum: str | None
    model_checksum: str | None
    vocab_checksum: str | None
    vocabulary_size: int | None
    pad_token_id: int | None
    bos_token_id: int | None
    eos_token_id: int | None
    unk_token_id: int | None
    tokenizer_type: str | None
    normalization_policy: str | None
    round_trip_status: str | None
    unknown_rate_status: str | None
    source_commit: str | None
    compatibility_fingerprint: str | None
    identity_fingerprint: str

    def as_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}

    @classmethod
    def create(cls, **values: object) -> TokenizerIdentity:
        code = "EOS_DIAG_TOKENIZER_IDENTITY_INVALID"
        expected = tuple(
            name
            for name in cls.__dataclass_fields__
            if name not in {"schema_version", "identity_fingerprint"}
        )
        mapping = _mapping(values, expected, code)
        for field in (
            "tokenizer_id",
            "tokenizer_type",
            "normalization_policy",
            "round_trip_status",
            "unknown_rate_status",
        ):
            _text(mapping[field], code, optional=True)
        _text(mapping["tokenizer_version"], code, optional=True, version=True)
        for field in (
            "tokenizer_fingerprint",
            "tokenizer_manifest_checksum",
            "model_checksum",
            "vocab_checksum",
            "compatibility_fingerprint",
        ):
            _fp(mapping[field], code, optional=True)
        _sha(mapping["source_commit"], code, optional=True)
        if mapping["vocabulary_size"] is not None and (
            type(mapping["vocabulary_size"]) is not int
            or mapping["vocabulary_size"] <= 0
        ):
            _fail(code)
        ids = tuple(
            mapping[field]
            for field in (
                "pad_token_id",
                "unk_token_id",
                "bos_token_id",
                "eos_token_id",
            )
        )
        if any(
            item is not None and (type(item) is not int or item < 0) for item in ids
        ):
            _fail(code)
        if all(item is not None for item in ids) and len(set(ids)) != 4:
            _fail(code)
        semantic = {"schema_version": EOS_DIAG_R2_SCHEMA_VERSION, **mapping}
        return cls(**semantic, identity_fingerprint=_identity_fingerprint(semantic))  # type: ignore[arg-type]

    @classmethod
    def from_mapping(cls, value: object) -> TokenizerIdentity:
        code = "EOS_DIAG_TOKENIZER_IDENTITY_INVALID"
        mapping = _mapping(value, cls.__dataclass_fields__, code)
        if mapping["schema_version"] != EOS_DIAG_R2_SCHEMA_VERSION:
            _fail(code)
        identity = cls.create(
            **{
                key: mapping[key]
                for key in mapping
                if key not in {"schema_version", "identity_fingerprint"}
            }
        )
        if _fp(mapping["identity_fingerprint"], code) != identity.identity_fingerprint:
            _fail(code)
        return identity


@dataclass(frozen=True)
class PromptSetIdentity:
    schema_version: int
    prompt_set_id: str | None
    prompt_set_version: str | None
    prompt_fingerprint: str | None
    prompt_count: int | None
    category_counts: tuple[tuple[str, int], ...] | None
    context_class_counts: tuple[tuple[str, int], ...] | None
    token_length_distribution: tuple[tuple[str, int], ...] | None
    normalization_policy: str | None
    pii_status: str | None
    leakage_status: str | None
    source_evidence_id: str | None
    source_evidence_fingerprint: str | None
    immutable: bool
    identity_fingerprint: str

    def as_dict(self) -> dict[str, object]:
        value = {field: getattr(self, field) for field in self.__dataclass_fields__}
        for field in (
            "category_counts",
            "context_class_counts",
            "token_length_distribution",
        ):
            pairs = value[field]
            value[field] = (
                None if pairs is None else {key: count for key, count in pairs}
            )
        return value

    @classmethod
    def create(cls, **values: object) -> PromptSetIdentity:
        code = "EOS_DIAG_PROMPT_SET_IDENTITY_INVALID"
        expected = tuple(
            name
            for name in cls.__dataclass_fields__
            if name not in {"schema_version", "identity_fingerprint"}
        )
        mapping = dict(_mapping(values, expected, code))
        for field in (
            "prompt_set_id",
            "normalization_policy",
            "pii_status",
            "leakage_status",
            "source_evidence_id",
        ):
            _text(mapping[field], code, optional=True)
        _text(mapping["prompt_set_version"], code, optional=True, version=True)
        _fp(mapping["prompt_fingerprint"], code, optional=True)
        _fp(mapping["source_evidence_fingerprint"], code, optional=True)
        if mapping["prompt_count"] is not None and (
            type(mapping["prompt_count"]) is not int or mapping["prompt_count"] <= 0
        ):
            _fail(code)
        for field in (
            "category_counts",
            "context_class_counts",
            "token_length_distribution",
        ):
            mapping[field] = _count_pairs(mapping[field], code)
        if type(mapping["immutable"]) is not bool:
            _fail(code)
        semantic_dict: dict[str, object] = {
            "schema_version": EOS_DIAG_R2_SCHEMA_VERSION,
            **mapping,
        }
        fingerprint_value = {
            **semantic_dict,
            "category_counts": None
            if mapping["category_counts"] is None
            else dict(mapping["category_counts"]),
            "context_class_counts": None
            if mapping["context_class_counts"] is None
            else dict(mapping["context_class_counts"]),
            "token_length_distribution": None
            if mapping["token_length_distribution"] is None
            else dict(mapping["token_length_distribution"]),
        }
        return cls(
            **semantic_dict,
            identity_fingerprint=_identity_fingerprint(fingerprint_value),
        )  # type: ignore[arg-type]

    @classmethod
    def from_mapping(cls, value: object) -> PromptSetIdentity:
        code = "EOS_DIAG_PROMPT_SET_IDENTITY_INVALID"
        mapping = _mapping(value, cls.__dataclass_fields__, code)
        if mapping["schema_version"] != EOS_DIAG_R2_SCHEMA_VERSION:
            _fail(code)
        identity = cls.create(
            **{
                key: mapping[key]
                for key in mapping
                if key not in {"schema_version", "identity_fingerprint"}
            }
        )
        if _fp(mapping["identity_fingerprint"], code) != identity.identity_fingerprint:
            _fail(code)
        return identity


@dataclass(frozen=True)
class BackendIdentity:
    schema_version: int
    backend_name: str | None
    backend_version: str | None
    source_commit: str | None
    module_fingerprints: tuple[tuple[str, str], ...] | None
    config_schema_version: str | None
    artifact_schema_version: str | None
    backend_fingerprint: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "backend_name": self.backend_name,
            "backend_version": self.backend_version,
            "source_commit": self.source_commit,
            "module_fingerprints": None
            if self.module_fingerprints is None
            else dict(self.module_fingerprints),
            "config_schema_version": self.config_schema_version,
            "artifact_schema_version": self.artifact_schema_version,
            "backend_fingerprint": self.backend_fingerprint,
        }

    @classmethod
    def create(cls, **values: object) -> BackendIdentity:
        code = "EOS_DIAG_BACKEND_IDENTITY_INVALID"
        expected = tuple(
            name
            for name in cls.__dataclass_fields__
            if name not in {"schema_version", "backend_fingerprint"}
        )
        mapping = dict(_mapping(values, expected, code))
        for field in ("backend_name",):
            _text(mapping[field], code, optional=True)
        for field in (
            "backend_version",
            "config_schema_version",
            "artifact_schema_version",
        ):
            _text(mapping[field], code, optional=True, version=True)
        _sha(mapping["source_commit"], code, optional=True)
        modules = mapping["module_fingerprints"]
        if modules is None:
            frozen_modules = None
        else:
            if type(modules) is not dict or not modules:
                _fail(code)
            frozen_modules = tuple(sorted(modules.items()))
            for name, value in frozen_modules:
                _text(name, code)
                _fp(value, code)
        mapping["module_fingerprints"] = frozen_modules
        semantic = {
            "schema_version": EOS_DIAG_R2_SCHEMA_VERSION,
            **mapping,
            "module_fingerprints": None
            if frozen_modules is None
            else dict(frozen_modules),
        }
        return cls(
            schema_version=EOS_DIAG_R2_SCHEMA_VERSION,
            backend_name=mapping["backend_name"],
            backend_version=mapping["backend_version"],
            source_commit=mapping["source_commit"],
            module_fingerprints=frozen_modules,
            config_schema_version=mapping["config_schema_version"],
            artifact_schema_version=mapping["artifact_schema_version"],
            backend_fingerprint=_identity_fingerprint(semantic),
        )  # type: ignore[arg-type]

    @classmethod
    def from_mapping(cls, value: object) -> BackendIdentity:
        code = "EOS_DIAG_BACKEND_IDENTITY_INVALID"
        mapping = _mapping(value, cls.__dataclass_fields__, code)
        if mapping["schema_version"] != EOS_DIAG_R2_SCHEMA_VERSION:
            _fail(code)
        identity = cls.create(
            **{
                key: mapping[key]
                for key in mapping
                if key not in {"schema_version", "backend_fingerprint"}
            }
        )
        if _fp(mapping["backend_fingerprint"], code) != identity.backend_fingerprint:
            _fail(code)
        return identity


@dataclass(frozen=True)
class DependencyEntry:
    name: str
    version: str
    required: bool
    source: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "required": self.required,
            "source": self.source,
        }

    @classmethod
    def from_mapping(cls, value: object) -> DependencyEntry:
        code = "EOS_DIAG_DEPENDENCY_IDENTITY_INVALID"
        mapping = _mapping(value, ("name", "version", "required", "source"), code)
        _text(mapping["name"], code)
        _text(mapping["version"], code, version=True)
        _text(mapping["source"], code)
        if type(mapping["required"]) is not bool:
            _fail(code)
        return cls(**mapping)


@dataclass(frozen=True)
class DependencyIdentity:
    schema_version: int
    python_version: str | None
    torch_version: str | None
    cuda_build: str | None
    cudnn_version: str | None
    platform: str | None
    dependency_entries: tuple[DependencyEntry, ...] | None
    dependency_fingerprint: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "python_version": self.python_version,
            "torch_version": self.torch_version,
            "cuda_build": self.cuda_build,
            "cudnn_version": self.cudnn_version,
            "platform": self.platform,
            "dependency_entries": None
            if self.dependency_entries is None
            else [entry.as_dict() for entry in self.dependency_entries],
            "dependency_fingerprint": self.dependency_fingerprint,
        }

    @classmethod
    def create(cls, **values: object) -> DependencyIdentity:
        code = "EOS_DIAG_DEPENDENCY_IDENTITY_INVALID"
        expected = tuple(
            name
            for name in cls.__dataclass_fields__
            if name not in {"schema_version", "dependency_fingerprint"}
        )
        mapping = _mapping(values, expected, code)
        for field in (
            "python_version",
            "torch_version",
            "cuda_build",
            "cudnn_version",
            "platform",
        ):
            _text(mapping[field], code, optional=True, version=True)
        raw_entries = mapping["dependency_entries"]
        if raw_entries is None:
            entries = None
        else:
            if type(raw_entries) not in {list, tuple} or not raw_entries:
                _fail(code)
            entries = tuple(
                sorted(
                    (
                        entry
                        if isinstance(entry, DependencyEntry)
                        else DependencyEntry.from_mapping(entry)
                        for entry in raw_entries
                    ),
                    key=lambda entry: entry.name,
                )
            )
            if len({entry.name for entry in entries}) != len(entries):
                _fail(code)
        semantic = {
            "schema_version": EOS_DIAG_R2_SCHEMA_VERSION,
            **{key: mapping[key] for key in mapping if key != "dependency_entries"},
            "dependency_entries": None
            if entries is None
            else [entry.as_dict() for entry in entries],
        }
        return cls(
            schema_version=EOS_DIAG_R2_SCHEMA_VERSION,
            python_version=mapping["python_version"],
            torch_version=mapping["torch_version"],
            cuda_build=mapping["cuda_build"],
            cudnn_version=mapping["cudnn_version"],
            platform=mapping["platform"],
            dependency_entries=entries,
            dependency_fingerprint=_identity_fingerprint(semantic),
        )  # type: ignore[arg-type]

    @classmethod
    def from_mapping(cls, value: object) -> DependencyIdentity:
        code = "EOS_DIAG_DEPENDENCY_IDENTITY_INVALID"
        mapping = _mapping(value, cls.__dataclass_fields__, code)
        if mapping["schema_version"] != EOS_DIAG_R2_SCHEMA_VERSION:
            _fail(code)
        identity = cls.create(
            **{
                key: mapping[key]
                for key in mapping
                if key not in {"schema_version", "dependency_fingerprint"}
            }
        )
        if (
            _fp(mapping["dependency_fingerprint"], code)
            != identity.dependency_fingerprint
        ):
            _fail(code)
        return identity


@dataclass(frozen=True)
class CandidateBEvaluationBinding:
    training_run_id: str
    checkpoint_checksum: str
    model_config_fingerprint: str
    evaluation_id: str
    evaluation_fingerprint: str
    architecture_id: str
    parameter_count: int
    tokenizer_fingerprint: str
    tokenizer_compatibility_fingerprint: str
    prompt_fingerprint: str
    training_source_commit: str


@dataclass(frozen=True)
class FreezeResult:
    component: str
    status: str
    identity_fingerprint: str
    blocking_reasons: tuple[str, ...]
    conditional_reasons: tuple[str, ...]


@dataclass(frozen=True)
class GateEvidence:
    gate_id: str
    status: str
    identity_fingerprints: tuple[tuple[str, str], ...]
    blocking_reasons: tuple[str, ...]
    conditional_reasons: tuple[str, ...]
    approved_next_actions: tuple[str, ...]
    prohibited_actions: tuple[str, ...]
    evidence_fingerprint: str

    def as_dict(self) -> dict[str, object]:
        return {
            "gate_id": self.gate_id,
            "status": self.status,
            "identity_fingerprints": dict(self.identity_fingerprints),
            "blocking_reasons": list(self.blocking_reasons),
            "conditional_reasons": list(self.conditional_reasons),
            "approved_next_actions": list(self.approved_next_actions),
            "prohibited_actions": list(self.prohibited_actions),
            "evidence_fingerprint": self.evidence_fingerprint,
        }


def _freeze_result(
    component: str,
    fingerprint: str,
    missing: Sequence[str],
    incompatible: Sequence[str],
) -> FreezeResult:
    if incompatible:
        status = "incompatible"
    elif missing:
        status = "incomplete"
    else:
        status = "frozen"
    return FreezeResult(
        component, status, fingerprint, tuple(sorted(incompatible or missing)), ()
    )


def freeze_checkpoint_identity(identity: CheckpointIdentity) -> FreezeResult:
    identity = CheckpointIdentity.from_mapping(identity.as_dict())
    required = tuple(
        field
        for field in identity.__dataclass_fields__
        if field not in {"schema_version", "identity_fingerprint", "immutable"}
        and getattr(identity, field) is None
    )
    incompatible = []
    if identity.immutable is not True:
        incompatible.append("checkpoint_not_immutable")
    return _freeze_result(
        "checkpoint_identity", identity.identity_fingerprint, required, incompatible
    )


def freeze_tokenizer_identity(identity: TokenizerIdentity) -> FreezeResult:
    identity = TokenizerIdentity.from_mapping(identity.as_dict())
    required = tuple(
        field
        for field in identity.__dataclass_fields__
        if field not in {"schema_version", "identity_fingerprint"}
        and getattr(identity, field) is None
    )
    incompatible = []
    if all(
        value is not None
        for value in (
            identity.pad_token_id,
            identity.unk_token_id,
            identity.bos_token_id,
            identity.eos_token_id,
        )
    ) and (
        identity.pad_token_id,
        identity.unk_token_id,
        identity.bos_token_id,
        identity.eos_token_id,
    ) != (0, 1, 2, 3):
        incompatible.append("special_token_contract_mismatch")
    if identity.vocabulary_size is not None and identity.vocabulary_size != 16000:
        incompatible.append("vocabulary_size_mismatch")
    return _freeze_result(
        "tokenizer_identity", identity.identity_fingerprint, required, incompatible
    )


def freeze_prompt_set_identity(identity: PromptSetIdentity) -> FreezeResult:
    identity = PromptSetIdentity.from_mapping(identity.as_dict())
    required = tuple(
        field
        for field in identity.__dataclass_fields__
        if field not in {"schema_version", "identity_fingerprint", "immutable"}
        and getattr(identity, field) is None
    )
    incompatible = []
    for field in (
        "category_counts",
        "context_class_counts",
        "token_length_distribution",
    ):
        pairs = getattr(identity, field)
        if (
            pairs is not None
            and identity.prompt_count is not None
            and sum(count for _, count in pairs) != identity.prompt_count
        ):
            incompatible.append(f"{field}_count_mismatch")
    if identity.immutable is not True:
        incompatible.append("prompt_set_not_immutable")
    if identity.pii_status not in {None, "synthetic_pii_free"}:
        incompatible.append("pii_status_unresolved")
    if identity.leakage_status not in {None, "synthetic_no_dataset_source"}:
        incompatible.append("leakage_status_unresolved")
    return _freeze_result(
        "prompt_set_identity", identity.identity_fingerprint, required, incompatible
    )


def freeze_backend_identity(identity: BackendIdentity) -> FreezeResult:
    identity = BackendIdentity.from_mapping(identity.as_dict())
    missing = tuple(
        field
        for field in (
            "backend_name",
            "backend_version",
            "source_commit",
            "module_fingerprints",
            "config_schema_version",
            "artifact_schema_version",
        )
        if getattr(identity, field) is None
    )
    return _freeze_result("backend_identity", identity.backend_fingerprint, missing, ())


def freeze_dependency_identity(identity: DependencyIdentity) -> FreezeResult:
    identity = DependencyIdentity.from_mapping(identity.as_dict())
    missing = tuple(
        field
        for field in (
            "python_version",
            "torch_version",
            "cuda_build",
            "cudnn_version",
            "platform",
            "dependency_entries",
        )
        if getattr(identity, field) is None
    )
    return _freeze_result(
        "dependency_identity", identity.dependency_fingerprint, missing, ()
    )


def _gate_evidence(
    gate_id: str, fingerprints: Mapping[str, str], blocking: Sequence[str]
) -> GateEvidence:
    status = "passed" if not blocking else "blocked"
    prohibited = (
        "checkpoint_load",
        "tokenizer_load",
        "prompt_payload_read",
        "gpu",
        "generation",
        "training",
        "approval_issue",
        "runtime_request_create",
    )
    approved = (
        ("synthetic_schema_rehearsal",)
        if status == "passed"
        else ("resolve_declared_evidence",)
    )
    semantic = {
        "gate_id": gate_id,
        "status": status,
        "identity_fingerprints": dict(sorted(fingerprints.items())),
        "blocking_reasons": sorted(blocking),
        "conditional_reasons": [],
        "approved_next_actions": list(approved),
        "prohibited_actions": list(prohibited),
    }
    return GateEvidence(
        gate_id,
        status,
        tuple(sorted(fingerprints.items())),
        tuple(sorted(blocking)),
        (),
        approved,
        prohibited,
        diagnostic_fingerprint(semantic),
    )


def evaluate_eos_diag_1(
    checkpoint: CheckpointIdentity,
    tokenizer: TokenizerIdentity,
    prompt_set: PromptSetIdentity,
    binding: CandidateBEvaluationBinding,
) -> GateEvidence:
    for field in ("training_run_id", "evaluation_id", "architecture_id"):
        _text(getattr(binding, field), "EOS_DIAG_IDENTITY_INCOMPATIBLE")
    for field in (
        "checkpoint_checksum",
        "model_config_fingerprint",
        "evaluation_fingerprint",
        "tokenizer_fingerprint",
        "tokenizer_compatibility_fingerprint",
        "prompt_fingerprint",
    ):
        _fp(getattr(binding, field), "EOS_DIAG_IDENTITY_INCOMPATIBLE")
    _sha(binding.training_source_commit, "EOS_DIAG_IDENTITY_INCOMPATIBLE")
    if type(binding.parameter_count) is not int or binding.parameter_count <= 0:
        _fail("EOS_DIAG_IDENTITY_INCOMPATIBLE")
    results = (
        freeze_checkpoint_identity(checkpoint),
        freeze_tokenizer_identity(tokenizer),
        freeze_prompt_set_identity(prompt_set),
    )
    blocking = [
        f"{result.component}:{reason}"
        for result in results
        for reason in result.blocking_reasons
    ]
    blocking.extend(
        f"{result.component}:{result.status}"
        for result in results
        if result.status != "frozen"
    )
    comparisons = {
        "training_run_id": (checkpoint.training_run_id, binding.training_run_id),
        "checkpoint_checksum": (
            checkpoint.checkpoint_checksum,
            binding.checkpoint_checksum,
        ),
        "model_config_fingerprint": (
            checkpoint.model_config_fingerprint,
            binding.model_config_fingerprint,
        ),
        "evaluation_id": (checkpoint.evaluation_id, binding.evaluation_id),
        "evaluation_fingerprint": (
            checkpoint.evaluation_fingerprint,
            binding.evaluation_fingerprint,
        ),
        "architecture_id": (checkpoint.architecture_id, binding.architecture_id),
        "parameter_count": (checkpoint.parameter_count, binding.parameter_count),
        "training_source_commit": (
            checkpoint.training_source_commit,
            binding.training_source_commit,
        ),
        "tokenizer_fingerprint": (
            tokenizer.tokenizer_fingerprint,
            binding.tokenizer_fingerprint,
        ),
        "tokenizer_compatibility_fingerprint": (
            tokenizer.compatibility_fingerprint,
            binding.tokenizer_compatibility_fingerprint,
        ),
        "prompt_fingerprint": (
            prompt_set.prompt_fingerprint,
            binding.prompt_fingerprint,
        ),
    }
    blocking.extend(
        f"lineage_mismatch:{field}"
        for field, pair in comparisons.items()
        if pair[0] != pair[1]
    )
    return _gate_evidence(
        "EOS-DIAG-1",
        {
            "checkpoint_identity": checkpoint.identity_fingerprint,
            "tokenizer_identity": tokenizer.identity_fingerprint,
            "prompt_set_identity": prompt_set.identity_fingerprint,
        },
        blocking,
    )


def evaluate_eos_diag_2(
    matrix: GenerationMatrix,
    backend: BackendIdentity,
    dependency: DependencyIdentity,
    *,
    artifact_set: Sequence[str],
    source_commit: str,
) -> GateEvidence:
    matrix = GenerationMatrix.from_mapping(matrix.as_dict())
    _sha(source_commit, "EOS_DIAG_IDENTITY_INCOMPATIBLE")
    blocking = []
    for result in (
        freeze_backend_identity(backend),
        freeze_dependency_identity(dependency),
    ):
        blocking.extend(
            f"{result.component}:{reason}" for reason in result.blocking_reasons
        )
        if result.status != "frozen":
            blocking.append(f"{result.component}:{result.status}")
    if tuple(artifact_set) != EXACT_ARTIFACT_FILENAMES:
        blocking.append("artifact_set_mismatch")
    if (
        matrix.expected_execution_count != 660
        or matrix.expected_trajectory_count != 165
    ):
        blocking.append("generation_matrix_count_mismatch")
    if backend.config_schema_version != str(EOS_DIAG_R2_SCHEMA_VERSION):
        blocking.append("config_schema_version_mismatch")
    if backend.artifact_schema_version != "1":
        blocking.append("artifact_schema_version_mismatch")
    if backend.source_commit != source_commit:
        blocking.append("source_commit_mismatch")
    return _gate_evidence(
        "EOS-DIAG-2",
        {
            "generation_matrix": matrix.matrix_fingerprint,
            "backend_identity": backend.backend_fingerprint,
            "dependency_identity": dependency.dependency_fingerprint,
            "artifact_set": diagnostic_fingerprint(list(artifact_set)),
            "source_commit_identity": diagnostic_fingerprint(source_commit),
        },
        blocking,
    )


def _require_r1_ready(
    gate_1: GateEvidence, gate_2: GateEvidence, source_commit: str
) -> None:
    _sha(source_commit, "EOS_DIAG_R1_PAYLOAD_INCOMPATIBLE")
    if (
        gate_1.gate_id != "EOS-DIAG-1"
        or gate_2.gate_id != "EOS-DIAG-2"
        or gate_1.status != "passed"
        or gate_2.status != "passed"
    ):
        _fail("EOS_DIAG_GATE_NOT_READY")
    for evidence in (gate_1, gate_2):
        if evidence.status not in GATE_STATUSES:
            _fail("EOS_DIAG_R1_PAYLOAD_INCOMPATIBLE")
        semantic = evidence.as_dict()
        semantic.pop("evidence_fingerprint")
        if diagnostic_fingerprint(semantic) != evidence.evidence_fingerprint:
            _fail("EOS_DIAG_R1_PAYLOAD_INCOMPATIBLE")


def build_r1_management_artifacts(
    *,
    diagnostic_run_id: str,
    created_at: str,
    source_commit: str,
    checkpoint: CheckpointIdentity,
    tokenizer: TokenizerIdentity,
    prompt_set: PromptSetIdentity,
    matrix: GenerationMatrix,
    gate_1: GateEvidence,
    gate_2: GateEvidence,
) -> tuple[DiagnosticArtifact, ...]:
    """Build only the six R1 management artifacts for a synthetic rehearsal."""
    _require_r1_ready(gate_1, gate_2, source_commit)
    if not diagnostic_run_id.startswith("SYNTHETIC-"):
        _fail("EOS_DIAG_R1_PAYLOAD_INCOMPATIBLE")
    if any(
        result.status != "frozen"
        for result in (
            freeze_checkpoint_identity(checkpoint),
            freeze_tokenizer_identity(tokenizer),
            freeze_prompt_set_identity(prompt_set),
        )
    ):
        _fail("EOS_DIAG_IDENTITY_INCOMPLETE")
    if dict(gate_1.identity_fingerprints) != {
        "checkpoint_identity": checkpoint.identity_fingerprint,
        "tokenizer_identity": tokenizer.identity_fingerprint,
        "prompt_set_identity": prompt_set.identity_fingerprint,
    }:
        _fail("EOS_DIAG_R1_PAYLOAD_INCOMPATIBLE")
    gate_2_fingerprints = dict(gate_2.identity_fingerprints)
    if (
        gate_2_fingerprints.get("generation_matrix") != matrix.matrix_fingerprint
        or gate_2_fingerprints.get("artifact_set")
        != diagnostic_fingerprint(list(EXACT_ARTIFACT_FILENAMES))
        or gate_2_fingerprints.get("source_commit_identity")
        != diagnostic_fingerprint(source_commit)
    ):
        _fail("EOS_DIAG_R1_PAYLOAD_INCOMPATIBLE")
    common = {
        "diagnostic_run_id": diagnostic_run_id,
        "checkpoint_identity_fingerprint": checkpoint.identity_fingerprint,
        "tokenizer_identity_fingerprint": tokenizer.identity_fingerprint,
        "prompt_set_fingerprint": prompt_set.identity_fingerprint,
        "generation_matrix_fingerprint": matrix.matrix_fingerprint,
        "source_commit": source_commit,
        "created_at": created_at,
    }
    profiles = []
    for profile in matrix.profiles:
        mode = {
            "pure_greedy": "pure_greedy",
            "sampling": "diagnostic_only_sampling",
            "assisted_decoding": "diagnostic_only_assisted",
        }[profile.mode]
        profiles.append(
            {
                "name": profile.profile_id,
                "mode": mode,
                "parameters": {
                    "do_sample": profile.do_sample,
                    "temperature": profile.temperature,
                    "top_k": profile.top_k,
                    "top_p": profile.top_p,
                    "repetition_penalty": profile.repetition_penalty,
                    "no_repeat_ngram": profile.no_repeat_ngram_size,
                    "forced_eos": False,
                    "logit_bias": False,
                    "heuristic_stop": False,
                },
            }
        )
    payloads: tuple[tuple[str, int, Mapping[str, object]], ...] = (
        (
            "diagnostic_run_manifest",
            1,
            {
                "purpose": "Synthetic identity and generation matrix schema rehearsal",
                "execution_mode": "synthetic_schema_rehearsal",
                "permissions": {
                    "checkpoint_load": False,
                    "tokenizer_load": False,
                    "gpu": False,
                    "generation": False,
                    "checkpoint_write": False,
                    "training": False,
                },
                "exact_artifact_set": list(EXACT_ARTIFACT_FILENAMES),
                "predecessor_diagnostic_run_id": None,
            },
        ),
        (
            "checkpoint_identity",
            1,
            {
                "checkpoint_id": checkpoint.checkpoint_id,
                "checkpoint_checksum": checkpoint.checkpoint_checksum,
                "checkpoint_manifest_fingerprint": checkpoint.checkpoint_manifest_fingerprint,
                "model_config_fingerprint": checkpoint.model_config_fingerprint,
                "training_run_id": checkpoint.training_run_id,
                "training_source_commit": checkpoint.training_source_commit,
                "full_evaluation_id": checkpoint.evaluation_id,
                "read_only": True,
            },
        ),
        (
            "tokenizer_identity",
            1,
            {
                "tokenizer_id": tokenizer.tokenizer_id,
                "bundle_checksum": tokenizer.tokenizer_manifest_checksum,
                "model_checksum": tokenizer.model_checksum,
                "vocab_checksum": tokenizer.vocab_checksum,
                "tokenizer_fingerprint": tokenizer.tokenizer_fingerprint,
                "vocab_size": tokenizer.vocabulary_size,
                "special_token_ids": {
                    "pad": tokenizer.pad_token_id,
                    "unk": tokenizer.unk_token_id,
                    "bos": tokenizer.bos_token_id,
                    "eos": tokenizer.eos_token_id,
                },
                "loaded": False,
            },
        ),
        (
            "prompt_set_identity",
            prompt_set.prompt_count,
            {
                "prompt_set_id": prompt_set.prompt_set_id,
                "version": prompt_set.prompt_set_version,
                "checksum": prompt_set.prompt_fingerprint,
                "prompt_count": prompt_set.prompt_count,
                "category_distribution": dict(prompt_set.category_counts or ()),
                "length_distribution": dict(prompt_set.token_length_distribution or ()),
                "normalization_policy": prompt_set.normalization_policy,
                "pii_status": prompt_set.pii_status,
                "leakage_status": prompt_set.leakage_status,
                "source_evidence": prompt_set.source_evidence_fingerprint,
                "prompt_text_stored": False,
            },
        ),
        (
            "generation_matrix",
            len(profiles),
            {
                "matrix_id": matrix.matrix_id,
                "device": matrix.device,
                "dtype": matrix.dtype,
                "seed": matrix.profiles[0].seed,
                "prompt_repetitions": matrix.prompt_repetitions,
                "lengths": list(matrix.length_values),
                "profiles": profiles,
                "stop_policy": {
                    "eos": True,
                    "maximum_new_tokens": True,
                    "external_heuristic": False,
                },
                "privacy": {
                    "raw_text_storage": False,
                    "raw_token_sequence_storage": False,
                },
            },
        ),
        (
            "output_manifest",
            len(EXACT_ARTIFACT_FILENAMES),
            {
                "status": "writing",
                "output_root_logical_id": "analysis/evaluation/diagnostics/synthetic-not-for-runtime",
                "writer_name": "dohalm-eos-diagnostic-artifact-writer",
                "writer_version": "1",
                "exact_artifact_set": list(EXACT_ARTIFACT_FILENAMES),
                "optional_artifact_set": [],
            },
        ),
    )
    try:
        return tuple(
            new_diagnostic_artifact(
                artifact_type=artifact_type,
                record_count=record_count,
                payload=payload,
                **common,
            )
            for artifact_type, record_count, payload in payloads
        )
    except Exception as exc:
        if isinstance(exc, EOSDiagnosticIdentityError):
            raise
        raise EOSDiagnosticIdentityError("EOS_DIAG_R1_PAYLOAD_INCOMPATIBLE") from None
