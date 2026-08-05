"""Synthetic-only, payload-free scanner contracts for V03-R2.

This module deliberately has no file, environment, network, or writer entry point.
Record text exists only on the transient input objects; results contain one-way
references and fingerprints.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .v03_evidence import v03_fingerprint

PII_CATEGORIES = (
    "resident_registration_number",
    "phone_number",
    "email",
    "postal_address",
    "bank_account",
    "card_number",
    "person_organization_combination",
    "user_identifier",
    "personal_url_identifier",
    "sensitive_free_text",
    "reconstruction_risk",
)
SAFETY_CATEGORIES = (
    "self_harm",
    "violence",
    "sexual_content",
    "hate_harassment",
    "illegal_activity",
    "privacy",
    "high_risk_advice",
    "child_sensitive",
    "prompt_injection",
    "evaluation_contamination",
)
LEAKAGE_CATEGORIES = (
    "exact_duplicate",
    "normalized_duplicate",
    "near_duplicate",
    "prompt_overlap",
    "answer_overlap",
    "duplicate_prompt",
    "duplicate_answer",
    "duplicate_qa_pair",
    "train_validation_overlap",
    "template_contamination",
    "prior_evaluation_overlap",
)
SEVERITIES = ("low", "medium", "high", "critical")
LOCATIONS = ("instruction", "output", "metadata", "cross_record")
STATUSES = (
    "detected",
    "reviewed",
    "excluded",
    "retained_with_review",
    "dismissed",
    "unresolved",
)
SPLITS = ("train", "validation")
SYNTHETIC_CREATED_AT = "1970-01-01T00:00:00Z"
_OPAQUE_RE = re.compile(r"opaque:v1:[0-9a-f]{64}\Z")
_MARKER = re.compile(r"\[synthetic-(pii|safety):([a-z_]+)\]", re.IGNORECASE)


class V03ScanningError(RuntimeError):
    """Fail-closed error whose message never includes caller-controlled values."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise V03ScanningError(code)


def _clean_string(value: object, *, code: str = "V03_SCAN_INPUT_INVALID") -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        _fail(code)
    return value


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        return MappingProxyType(dict(value))
    except (TypeError, ValueError):
        _fail("V03_SCAN_INPUT_INVALID")


@dataclass(frozen=True)
class SyntheticRecord:
    source_record_id: str = field(repr=False)
    split: str
    instruction: str = field(repr=False)
    output: str = field(repr=False)
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    source_fingerprint: str = ""

    def __post_init__(self) -> None:
        _clean_string(self.source_record_id)
        if self.split not in SPLITS:
            _fail("V03_SCAN_INPUT_INVALID")
        _clean_string(self.instruction)
        _clean_string(self.output)
        if type(self.metadata) is not dict:
            _fail("V03_SCAN_INPUT_INVALID")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.source_fingerprint):
            _fail("V03_SCAN_INPUT_INVALID")


@dataclass(frozen=True)
class SyntheticBenchmarkRecord:
    benchmark_record_id: str = field(repr=False)
    instruction: str = field(repr=False)
    output: str = field(repr=False)
    benchmark_id: str
    benchmark_version: str
    source_fingerprint: str

    def __post_init__(self) -> None:
        for value in (
            self.benchmark_record_id,
            self.instruction,
            self.output,
            self.benchmark_id,
            self.benchmark_version,
        ):
            _clean_string(value)
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.source_fingerprint):
            _fail("V03_SCAN_INPUT_INVALID")


def make_opaque_record_reference(
    *, dataset_id: str, source_record_id: str, namespace: str, secret: bytes
) -> str:
    """Return a domain-separated HMAC reference without retaining its inputs."""
    for value in (dataset_id, source_record_id, namespace):
        _clean_string(value, code="V03_OPAQUE_REFERENCE_INVALID")
    if type(secret) is not bytes or len(secret) < 32:
        _fail("V03_OPAQUE_REFERENCE_INVALID")
    message = (
        b"dohalm:v03:opaque-reference:v1\x00"
        + namespace.encode()
        + b"\x00"
        + dataset_id.encode()
        + b"\x00"
        + source_record_id.encode()
    )
    return "opaque:v1:" + hmac.new(secret, message, hashlib.sha256).hexdigest()


def normalize_leakage_text(text: str, *, lowercase_latin: bool = True) -> str:
    _clean_string(text)
    value = unicodedata.normalize("NFC", text).strip()
    value = re.sub(r"\s+", " ", value)
    return value.lower() if lowercase_latin else value


def normalize_pii_match(text: str) -> str:
    _clean_string(text)
    return re.sub(r"[\s().-]+", "", unicodedata.normalize("NFC", text)).lower()


def _secret_hash(value: str, *, namespace: str, secret: bytes) -> str:
    digest = hmac.new(
        secret,
        b"dohalm:v03:finding:v1\x00" + namespace.encode() + b"\x00" + value.encode(),
        hashlib.sha256,
    )
    return "hmac-sha256:" + digest.hexdigest()


@dataclass(frozen=True)
class PIIScannerConfig:
    schema_version: int = 1
    detector_version: str = "v03-r2-synthetic-pii-v1"
    enabled_categories: tuple[str, ...] = PII_CATEGORIES
    normalization_policy: str = "pii-nfc-strip-separators-v1"
    severity_mapping: tuple[tuple[str, str], ...] = (
        ("resident_registration_number", "critical"),
        ("phone_number", "high"),
        ("email", "high"),
        ("postal_address", "high"),
        ("bank_account", "critical"),
        ("card_number", "critical"),
        ("person_organization_combination", "high"),
        ("user_identifier", "medium"),
        ("personal_url_identifier", "medium"),
        ("sensitive_free_text", "high"),
        ("reconstruction_risk", "high"),
    )

    def __post_init__(self) -> None:
        _validate_config(
            self.schema_version,
            self.detector_version,
            self.enabled_categories,
            PII_CATEGORIES,
            self.severity_mapping,
        )

    @property
    def fingerprint(self) -> str:
        return v03_fingerprint(
            {name: getattr(self, name) for name in self.__dataclass_fields__}
        )


@dataclass(frozen=True)
class SafetyScannerConfig:
    schema_version: int = 1
    detector_version: str = "v03-r2-synthetic-safety-v1"
    enabled_categories: tuple[str, ...] = SAFETY_CATEGORIES
    normalization_policy: str = "safety-nfc-casefold-v1"
    severity_mapping: tuple[tuple[str, str], ...] = tuple(
        (
            name,
            "high"
            if name
            in {
                "self_harm",
                "child_sensitive",
                "prompt_injection",
                "evaluation_contamination",
            }
            else "medium",
        )
        for name in SAFETY_CATEGORIES
    )

    def __post_init__(self) -> None:
        _validate_config(
            self.schema_version,
            self.detector_version,
            self.enabled_categories,
            SAFETY_CATEGORIES,
            self.severity_mapping,
        )

    @property
    def fingerprint(self) -> str:
        return v03_fingerprint(
            {name: getattr(self, name) for name in self.__dataclass_fields__}
        )


@dataclass(frozen=True)
class LeakageScannerConfig:
    schema_version: int = 1
    detector_version: str = "v03-r2-synthetic-leakage-v1"
    enabled_categories: tuple[str, ...] = LEAKAGE_CATEGORIES
    normalization_policy: str = "leakage-nfc-whitespace-latin-lower-v1"
    near_duplicate_metric: str = "token_set_jaccard"
    near_duplicate_threshold: float = 0.8

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or not self.detector_version
            or set(self.enabled_categories) - set(LEAKAGE_CATEGORIES)
        ):
            _fail("V03_SCAN_CONFIG_INVALID")
        if (
            self.near_duplicate_metric
            not in {"token_set_jaccard", "character_3gram_jaccard"}
            or type(self.near_duplicate_threshold) is not float
            or not 0 < self.near_duplicate_threshold <= 1
        ):
            _fail("V03_SCAN_CONFIG_INVALID")

    @property
    def fingerprint(self) -> str:
        return v03_fingerprint(
            {name: getattr(self, name) for name in self.__dataclass_fields__}
        )


def _validate_config(
    schema: int,
    version: str,
    enabled: Sequence[str],
    allowed: Sequence[str],
    mapping: Sequence[tuple[str, str]],
) -> None:
    if (
        schema != 1
        or not version
        or not enabled
        or len(enabled) != len(set(enabled))
        or set(enabled) - set(allowed)
    ):
        _fail("V03_SCAN_CONFIG_INVALID")
    if set(dict(mapping)) != set(allowed) or any(
        value not in SEVERITIES for value in dict(mapping).values()
    ):
        _fail("V03_SCAN_CONFIG_INVALID")


DEFAULT_PII_SCANNER_CONFIG = PIIScannerConfig()
DEFAULT_SAFETY_SCANNER_CONFIG = SafetyScannerConfig()
DEFAULT_LEAKAGE_SCANNER_CONFIG = LeakageScannerConfig()


@dataclass(frozen=True)
class ScannerFinding:
    finding_id: str
    scanner_type: str
    scanner_version: str
    category: str
    severity: str
    opaque_record_reference: str
    split: str
    location: str
    detector: str
    confidence: float
    status: str
    reason_code: str
    evidence_fingerprint: str
    normalized_match_hash: str | None
    created_at: str = field(compare=False)

    def __post_init__(self) -> None:
        if (
            self.severity not in SEVERITIES
            or self.location not in LOCATIONS
            or self.status not in STATUSES
            or not _OPAQUE_RE.fullmatch(self.opaque_record_reference)
        ):
            _fail("V03_SCAN_FAILED")


@dataclass(frozen=True)
class ScannerResult:
    scanner_type: str
    scanner_version: str
    config_fingerprint: str
    input_dataset_fingerprint: str
    scanned_record_count: int
    findings: tuple[ScannerFinding, ...]
    findings_fingerprint: str
    category_counts: Mapping[str, int]
    severity_counts: Mapping[str, int]
    created_at: str = field(compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "category_counts", MappingProxyType(dict(self.category_counts))
        )
        object.__setattr__(
            self, "severity_counts", MappingProxyType(dict(self.severity_counts))
        )


def _result(
    scanner_type: str,
    version: str,
    config_fp: str,
    dataset_fp: str,
    count: int,
    findings: Iterable[ScannerFinding],
    categories: Sequence[str],
    created_at: str,
) -> ScannerResult:
    ordered = tuple(
        sorted(
            findings,
            key=lambda item: (
                item.opaque_record_reference,
                item.location,
                item.category,
                item.finding_id,
            ),
        )
    )
    category_counts = {
        name: sum(item.category == name for item in ordered) for name in categories
    }
    severity_counts = {
        name: sum(item.severity == name for item in ordered) for name in SEVERITIES
    }
    fingerprint = v03_fingerprint([_finding_identity(item) for item in ordered])
    return ScannerResult(
        scanner_type,
        version,
        config_fp,
        dataset_fp,
        count,
        ordered,
        fingerprint,
        category_counts,
        severity_counts,
        created_at,
    )


def _finding_identity(item: ScannerFinding) -> dict[str, Any]:
    return {
        name: getattr(item, name)
        for name in item.__dataclass_fields__
        if name != "created_at"
    }


def _make_finding(
    *,
    scanner_type: str,
    version: str,
    category: str,
    severity: str,
    record_ref: str,
    split: str,
    location: str,
    detector: str,
    evidence_value: str,
    secret: bytes,
    created_at: str,
    confidence: float = 1.0,
) -> ScannerFinding:
    match_hash = _secret_hash(
        evidence_value, namespace=f"{scanner_type}:match", secret=secret
    )
    base = {
        "scanner_type": scanner_type,
        "scanner_version": version,
        "category": category,
        "severity": severity,
        "opaque_record_reference": record_ref,
        "split": split,
        "location": location,
        "detector": detector,
        "confidence": confidence,
        "status": "detected",
        "reason_code": f"{category.upper()}_CANDIDATE",
        "normalized_match_hash": match_hash,
    }
    evidence_fp = v03_fingerprint(base)
    finding_id = "finding:v1:" + hashlib.sha256(evidence_fp.encode()).hexdigest()
    return ScannerFinding(
        finding_id=finding_id,
        evidence_fingerprint=evidence_fp,
        created_at=created_at,
        **base,
    )


def _record_fields(record: SyntheticRecord) -> tuple[tuple[str, str], ...]:
    metadata = " ".join(
        f"{key}={value}" for key, value in sorted(record.metadata.items())
    )
    return (
        ("instruction", record.instruction),
        ("output", record.output),
        ("metadata", metadata),
    )


def _validate_scan_inputs(
    dataset_id: object,
    input_dataset_fingerprint: object,
    records: object,
    secret: object,
) -> Sequence[SyntheticRecord]:
    _clean_string(dataset_id)
    if (
        type(input_dataset_fingerprint) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", input_dataset_fingerprint) is None
    ):
        _fail("V03_SCAN_INPUT_INVALID")
    if not isinstance(records, (list, tuple)) or any(
        not isinstance(item, SyntheticRecord) for item in records
    ):
        _fail("V03_SCAN_INPUT_INVALID")
    source_ids = [item.source_record_id for item in records]
    if len(source_ids) != len(set(source_ids)):
        _fail("V03_SCAN_INPUT_INVALID")
    if type(secret) is not bytes or len(secret) < 32:
        _fail("V03_OPAQUE_REFERENCE_INVALID")
    return records


def scan_pii_records(
    *,
    dataset_id: str,
    input_dataset_fingerprint: str,
    records: Sequence[SyntheticRecord],
    secret: bytes,
    config: PIIScannerConfig = DEFAULT_PII_SCANNER_CONFIG,
    created_at: str = SYNTHETIC_CREATED_AT,
) -> ScannerResult:
    records = _validate_scan_inputs(
        dataset_id, input_dataset_fingerprint, records, secret
    )
    severities = dict(config.severity_mapping)
    findings: list[ScannerFinding] = []
    patterns = {
        "email": re.compile(
            r"\b[a-z0-9._%+-]+@example\.(?:invalid|test)\b", re.IGNORECASE
        ),
        "phone_number": re.compile(r"\b000[- ]?0000[- ]?0000\b"),
        "resident_registration_number": re.compile(r"\b000000[- ]?0000000\b"),
        "card_number": re.compile(r"\b0000[- ]0000[- ]0000[- ]0000\b"),
        "bank_account": re.compile(r"\b000[- ]000000[- ]00\b"),
    }
    for record in records:
        ref = make_opaque_record_reference(
            dataset_id=dataset_id,
            source_record_id=record.source_record_id,
            namespace="pii",
            secret=secret,
        )
        for location, text in _record_fields(record):
            candidates: list[tuple[str, str, str]] = []
            for match in _MARKER.finditer(text):
                if (
                    match.group(1).lower() == "pii"
                    and match.group(2).lower() in config.enabled_categories
                ):
                    candidates.append(
                        (match.group(2).lower(), match.group(0), "synthetic_marker")
                    )
            for category, pattern in patterns.items():
                if category in config.enabled_categories:
                    candidates.extend(
                        (category, match.group(0), f"synthetic_{category}_regex")
                        for match in pattern.finditer(text)
                    )
            for category, raw, detector in candidates:
                findings.append(
                    _make_finding(
                        scanner_type="pii",
                        version=config.detector_version,
                        category=category,
                        severity=severities[category],
                        record_ref=ref,
                        split=record.split,
                        location=location,
                        detector=detector,
                        evidence_value=normalize_pii_match(raw),
                        secret=secret,
                        created_at=created_at,
                    )
                )
    return _result(
        "pii",
        config.detector_version,
        config.fingerprint,
        input_dataset_fingerprint,
        len(records),
        findings,
        PII_CATEGORIES,
        created_at,
    )


def scan_safety_records(
    *,
    dataset_id: str,
    input_dataset_fingerprint: str,
    records: Sequence[SyntheticRecord],
    secret: bytes,
    config: SafetyScannerConfig = DEFAULT_SAFETY_SCANNER_CONFIG,
    created_at: str = SYNTHETIC_CREATED_AT,
) -> ScannerResult:
    records = _validate_scan_inputs(
        dataset_id, input_dataset_fingerprint, records, secret
    )
    severities = dict(config.severity_mapping)
    findings: list[ScannerFinding] = []
    for record in records:
        ref = make_opaque_record_reference(
            dataset_id=dataset_id,
            source_record_id=record.source_record_id,
            namespace="safety",
            secret=secret,
        )
        for location, text in _record_fields(record):
            for match in _MARKER.finditer(text):
                category = match.group(2).lower()
                if (
                    match.group(1).lower() == "safety"
                    and category in config.enabled_categories
                ):
                    findings.append(
                        _make_finding(
                            scanner_type="safety",
                            version=config.detector_version,
                            category=category,
                            severity=severities[category],
                            record_ref=ref,
                            split=record.split,
                            location=location,
                            detector="synthetic_keyword_marker",
                            evidence_value=normalize_leakage_text(match.group(0)),
                            secret=secret,
                            created_at=created_at,
                        )
                    )
    return _result(
        "safety",
        config.detector_version,
        config.fingerprint,
        input_dataset_fingerprint,
        len(records),
        findings,
        SAFETY_CATEGORIES,
        created_at,
    )


def _jaccard(left: str, right: str, metric: str) -> float:
    if metric == "token_set_jaccard":
        a, b = set(left.split()), set(right.split())
    else:
        a = {left[i : i + 3] for i in range(max(1, len(left) - 2))}
        b = {right[i : i + 3] for i in range(max(1, len(right) - 2))}
    return len(a & b) / len(a | b) if a | b else 1.0


def scan_leakage_records(
    *,
    dataset_id: str,
    input_dataset_fingerprint: str,
    records: Sequence[SyntheticRecord],
    benchmark_records: Sequence[SyntheticBenchmarkRecord],
    secret: bytes,
    config: LeakageScannerConfig = DEFAULT_LEAKAGE_SCANNER_CONFIG,
    created_at: str = SYNTHETIC_CREATED_AT,
) -> ScannerResult:
    records = _validate_scan_inputs(
        dataset_id, input_dataset_fingerprint, records, secret
    )
    if not isinstance(benchmark_records, (list, tuple)) or any(
        not isinstance(item, SyntheticBenchmarkRecord) for item in benchmark_records
    ):
        _fail("V03_SCAN_INPUT_INVALID")
    benchmark_ids = [item.benchmark_record_id for item in benchmark_records]
    if len(benchmark_ids) != len(set(benchmark_ids)):
        _fail("V03_SCAN_INPUT_INVALID")
    findings: list[ScannerFinding] = []
    entries = [
        (
            record,
            normalize_leakage_text(record.instruction),
            normalize_leakage_text(record.output),
        )
        for record in records
    ]
    comparisons: list[tuple[SyntheticRecord, str, str, str, str, str]] = []
    for index, (left, lp, la) in enumerate(entries):
        for right, rp, ra in entries[index + 1 :]:
            comparisons.append(
                (left, right.source_record_id, rp, ra, "dataset", right.split)
            )
        for bench in benchmark_records:
            comparisons.append(
                (
                    left,
                    bench.benchmark_record_id,
                    normalize_leakage_text(bench.instruction),
                    normalize_leakage_text(bench.output),
                    "benchmark",
                    "benchmark",
                )
            )
    for left, other_id, rp, ra, source, other_split in comparisons:
        lp, la = (
            normalize_leakage_text(left.instruction),
            normalize_leakage_text(left.output),
        )
        categories: set[str] = set()
        exact_pair = left.instruction == (
            rp
            if source == "dataset"
            else next(
                (
                    b.instruction
                    for b in benchmark_records
                    if b.benchmark_record_id == other_id
                ),
                rp,
            )
        ) and left.output == (
            ra
            if source == "dataset"
            else next(
                (
                    b.output
                    for b in benchmark_records
                    if b.benchmark_record_id == other_id
                ),
                ra,
            )
        )
        if (lp, la) == (rp, ra):
            categories.add("exact_duplicate" if exact_pair else "normalized_duplicate")
        if lp == rp:
            categories.update({"prompt_overlap", "duplicate_prompt"})
        if la == ra:
            categories.update({"answer_overlap", "duplicate_answer"})
        if lp == rp and la == ra:
            categories.add("duplicate_qa_pair")
        if source == "dataset" and left.split != other_split and categories:
            categories.add("train_validation_overlap")
        similarity = (
            _jaccard(lp, rp, config.near_duplicate_metric)
            + _jaccard(la, ra, config.near_duplicate_metric)
        ) / 2
        if (
            similarity >= config.near_duplicate_threshold
            and not {"exact_duplicate", "normalized_duplicate"} & categories
        ):
            categories.add("near_duplicate")
        if source == "benchmark" and categories:
            categories.add("prior_evaluation_overlap")
        if (
            source == "benchmark"
            and "synthetic-template" in lp
            and "synthetic-template" in rp
        ):
            categories.add("template_contamination")
        if not categories:
            continue
        ref = make_opaque_record_reference(
            dataset_id=dataset_id,
            source_record_id=left.source_record_id,
            namespace="leakage",
            secret=secret,
        )
        pair_hash = _secret_hash(
            left.source_record_id + "\x00" + other_id,
            namespace="leakage:pair",
            secret=secret,
        )
        for category in sorted(categories & set(config.enabled_categories)):
            findings.append(
                _make_finding(
                    scanner_type="leakage",
                    version=config.detector_version,
                    category=category,
                    severity="high"
                    if category
                    in {
                        "exact_duplicate",
                        "normalized_duplicate",
                        "train_validation_overlap",
                        "prior_evaluation_overlap",
                    }
                    else "medium",
                    record_ref=ref,
                    split=left.split,
                    location="cross_record",
                    detector=f"synthetic_{config.near_duplicate_metric}",
                    evidence_value=pair_hash + category,
                    secret=secret,
                    created_at=created_at,
                    confidence=round(similarity, 6),
                )
            )
    return _result(
        "leakage",
        config.detector_version,
        config.fingerprint,
        input_dataset_fingerprint,
        len(records),
        findings,
        LEAKAGE_CATEGORIES,
        created_at,
    )
