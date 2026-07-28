"""Aggregate-only PII candidate scan for approved AIHUB-71748 SFT fields."""

from __future__ import annotations

import ipaddress
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from src.data.aihub_71748_join import (
    EXPECTED_RECORDS,
    JoinIntegrityError,
    _archive_contract,
    _entry_for,
    _iter_data_info,
)
from src.data.safety import guard_safe_output


DATASET_ID = 71748
EXECUTION_ID = "AIHUB-71748-PII-SCAN-20260729-0002"
ALLOWED_FIELDS = {
    "sftdata": (("question",),),
    "sftlabel": (("question",), ("answer", "contents")),
}
OUTPUT_FIELD_PATHS = {
    ("sftdata", ("question",)): "$.sftdata.question",
    ("sftlabel", ("question",)): "$.sftlabel.question",
    ("sftlabel", ("answer", "contents")): "$.sftlabel.answer.contents",
}
ALLOWED_OUTPUT_FIELD_PATHS = frozenset(OUTPUT_FIELD_PATHS.values())
DIRECT_TYPES = frozenset({
    "email", "phone", "resident_id_like", "passport_like", "driver_license_like",
    "address", "postal_code", "account_number_like", "card_number_like",
    "vehicle_number_like", "ip_address", "url", "social_handle",
})
QUASI_TYPES = frozenset({"birth_date", "person_name_candidate", "organization_role_combination"})
SENSITIVE_TYPES = frozenset({
    "medical_sensitive_candidate", "mental_health_candidate", "legal_sensitive_candidate",
    "financial_sensitive_candidate", "religion_candidate", "political_candidate",
    "family_relation_candidate",
})
CANDIDATE_TYPES = tuple(sorted(DIRECT_TYPES | QUASI_TYPES | SENSITIVE_TYPES | {"other"}))

_PATTERNS = {
    "email": re.compile(r"(?<![\w.])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.])"),
    "phone": re.compile(r"(?<!\d)(?:0(?:1[016789]|2|[3-6][1-5]))[- .]?\d{3,4}[- .]?\d{4}(?!\d)"),
    "passport_like": re.compile(r"(?<![A-Z0-9])[MS][0-9]{8}(?![A-Z0-9])", re.IGNORECASE),
    "driver_license_like": re.compile(r"(?<!\d)\d{2}[- ]\d{2}[- ]\d{6}[- ]\d{2}(?!\d)"),
    "birth_date": re.compile(r"(?<!\d)(?:19|20)\d{2}[-./년 ](?:0?[1-9]|1[0-2])[-./월 ](?:0?[1-9]|[12]\d|3[01])(?:일)?(?!\d)"),
    "address": re.compile(r"(?:[가-힣]+(?:특별시|광역시|특별자치시|도)\s+)?[가-힣0-9]+(?:시|군|구)\s+[가-힣0-9]+(?:로|길|동)(?:\s+\d+)?"),
    "postal_code": re.compile(r"(?<!\d)\d{5}(?!\d)"),
    "vehicle_number_like": re.compile(r"(?<![가-힣0-9])(?:[가-힣]{2}\s*)?\d{2,3}[가-힣]\d{4}(?!\d)"),
    "url": re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE),
    "social_handle": re.compile(r"(?<![\w@])@[A-Za-z0-9_]{3,32}(?!\w)"),
    "person_name_candidate": re.compile(r"(?:이름|성명)\s*[:：]?\s*[가-힣]{2,4}"),
    "organization_role_combination": re.compile(r"(?:학교|대학교|회사|병원|법원|기관|재단|협회|연구원).{0,20}(?:교사|교수|직원|의사|간호사|대표|부장|과장|팀장|판사|검사)"),
    "medical_sensitive_candidate": re.compile(r"(?:진단|질환|질병|수술|투약|처방|입원|암|당뇨|고혈압|장애)"),
    "mental_health_candidate": re.compile(r"(?:정신건강|우울증|조현병|불안장애|공황장애|자해|자살)"),
    "legal_sensitive_candidate": re.compile(r"(?:피고인|피의자|형사사건|민사사건|범죄|기소|유죄|전과)"),
    "financial_sensitive_candidate": re.compile(r"(?:계좌|대출|채무|신용등급|연체|파산|금융거래)"),
    "religion_candidate": re.compile(r"(?:종교|기독교|천주교|불교|이슬람|교회|성당|사찰)"),
    "political_candidate": re.compile(r"(?:정당|정치성향|보수성향|진보성향|당원)"),
    "family_relation_candidate": re.compile(r"(?:부모|부친|모친|배우자|남편|아내|자녀|아들|딸|형제|자매|가족관계)"),
}
_RRN = re.compile(r"(?<!\d)(\d{6})[- ]?([1-8]\d{6})(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_ACCOUNT = re.compile(r"(?<!\d)\d{2,6}-\d{2,6}-\d{2,6}(?:-\d{1,4})?(?!\d)")
_IP = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")


class PiiScanError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _luhn(digits: str) -> bool:
    total = 0
    parity = len(digits) % 2
    for index, character in enumerate(digits):
        value = int(character)
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _valid_rrn(first: str, second: str) -> bool:
    month, day = int(first[2:4]), int(first[4:6])
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return False
    digits = [int(value) for value in first + second]
    checksum = (11 - sum(value * weight for value, weight in zip(digits[:12], (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5))) % 11) % 10
    return checksum == digits[12]


def _detect_text(value: str) -> dict[str, Any]:
    occurrences: Counter[str] = Counter()
    for candidate_type, pattern in _PATTERNS.items():
        occurrences[candidate_type] += sum(1 for _ in pattern.finditer(value))
    occurrences["resident_id_like"] += sum(1 for match in _RRN.finditer(value) if _valid_rrn(match.group(1), match.group(2)))
    occurrences["card_number_like"] += sum(
        1 for match in _CARD.finditer(value)
        if 13 <= len((digits := re.sub(r"\D", "", match.group(0)))) <= 19 and _luhn(digits)
    )
    occurrences["account_number_like"] += sum(1 for _ in _ACCOUNT.finditer(value))
    occurrences["ip_address"] += sum(
        1 for match in _IP.finditer(value) if _valid_ip(match.group(0))
    )
    cleaned = Counter({key: count for key, count in occurrences.items() if count})
    return {"occurrences": dict(sorted(cleaned.items())), "types": sorted(cleaned)}


def _valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _risk(types: set[str]) -> str:
    direct = types & DIRECT_TYPES
    quasi = types & QUASI_TYPES
    sensitive = types & SENSITIVE_TYPES
    if "resident_id_like" in types or "card_number_like" in types or len(direct) >= 3:
        return "critical"
    if len(direct) >= 2 or (direct and sensitive):
        return "high"
    if direct or len(quasi) >= 2:
        return "medium"
    if quasi or sensitive:
        return "low"
    return "none"


def _field_value(record: dict[str, Any], path: tuple[str, ...]) -> str:
    value: Any = record
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise PiiScanError("PII_FIELD_MISSING")
        value = value[key]
    if not isinstance(value, str):
        raise PiiScanError("PII_FIELD_TYPE_MISMATCH")
    return value


def _new_field_summary() -> dict[str, Any]:
    return {"scanned_records": 0, "suspected_records": 0, "occurrences": 0, "minimum_length": None, "maximum_length": None}


def _safe_output_field_path(component: str, path: tuple[str, ...]) -> str:
    try:
        result = OUTPUT_FIELD_PATHS[(component, path)]
    except KeyError:
        raise PiiScanError("UNSAFE_OUTPUT_STRING") from None
    if result not in ALLOWED_OUTPUT_FIELD_PATHS:
        raise PiiScanError("UNSAFE_OUTPUT_STRING")
    return result


def _scan_once(package_root: Path) -> dict[str, Any]:
    archives = _archive_contract(package_root)
    fields: dict[str, dict[str, Any]] = {}
    splits = {split: {"scanned_records": 0, "suspected_records": 0} for split in EXPECTED_RECORDS}
    components = {component: {"scanned_records": 0, "suspected_records": 0} for component in ALLOWED_FIELDS}
    type_occurrences = Counter({key: 0 for key in CANDIDATE_TYPES})
    type_records = Counter({key: 0 for key in CANDIDATE_TYPES})
    risk_levels = Counter({key: 0 for key in ("none", "low", "medium", "high", "critical")})
    summary = Counter(scanned_records=0, scanned_fields=0, records_with_any_candidate=0, records_with_multiple_candidate_types=0)
    groups = Counter(direct_identifier_records=0, quasi_identifier_records=0, sensitive_information_records=0)
    combinations = Counter(person_phone=0, person_address=0, birth_address=0, medical_person=0, account_person=0)

    for split in ("training", "validation"):
        for component in ("sftdata", "sftlabel"):
            record_count = 0
            try:
                with zipfile.ZipFile(archives[(split, component)]) as archive:
                    with archive.open(_entry_for(archive, component), "r") as source:
                        for record in _iter_data_info(source):
                            record_count += 1
                            summary["scanned_records"] += 1
                            splits[split]["scanned_records"] += 1
                            components[component]["scanned_records"] += 1
                            record_types: set[str] = set()
                            source_values: list[str] = []
                            for path in ALLOWED_FIELDS[component]:
                                value = _field_value(record, path)
                                source_values.append(value)
                                field_name = _safe_output_field_path(component, path)
                                field = fields.setdefault(field_name, {
                                    "total": _new_field_summary(),
                                    "training": _new_field_summary(),
                                    "validation": _new_field_summary(),
                                })
                                detected = _detect_text(value)
                                field_types = set(detected["types"])
                                occurrences = sum(detected["occurrences"].values())
                                for scope in (field["total"], field[split]):
                                    scope["scanned_records"] += 1
                                    scope["suspected_records"] += bool(field_types)
                                    scope["occurrences"] += occurrences
                                    length = len(value)
                                    scope["minimum_length"] = length if scope["minimum_length"] is None else min(scope["minimum_length"], length)
                                    scope["maximum_length"] = length if scope["maximum_length"] is None else max(scope["maximum_length"], length)
                                summary["scanned_fields"] += 1
                                type_occurrences.update(detected["occurrences"])
                                record_types.update(field_types)
                            guarded = guard_safe_output({"types": sorted(record_types), "status": "ok"}, source_values)
                            if guarded is not None:
                                raise PiiScanError(guarded["error_code"])
                            for candidate_type in record_types:
                                type_records[candidate_type] += 1
                            has_candidate = bool(record_types)
                            summary["records_with_any_candidate"] += has_candidate
                            summary["records_with_multiple_candidate_types"] += len(record_types) > 1
                            splits[split]["suspected_records"] += has_candidate
                            components[component]["suspected_records"] += has_candidate
                            risk_levels[_risk(record_types)] += 1
                            groups["direct_identifier_records"] += bool(record_types & DIRECT_TYPES)
                            groups["quasi_identifier_records"] += bool(record_types & QUASI_TYPES)
                            groups["sensitive_information_records"] += bool(record_types & SENSITIVE_TYPES)
                            combinations["person_phone"] += {"person_name_candidate", "phone"} <= record_types
                            combinations["person_address"] += {"person_name_candidate", "address"} <= record_types
                            combinations["birth_address"] += {"birth_date", "address"} <= record_types
                            combinations["medical_person"] += "medical_sensitive_candidate" in record_types and "person_name_candidate" in record_types
                            combinations["account_person"] += "account_number_like" in record_types and "person_name_candidate" in record_types
                            source_values.clear()
                            record.clear()
            except PiiScanError:
                raise
            except JoinIntegrityError as exc:
                raise PiiScanError(exc.code) from None
            except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
                raise PiiScanError("PII_ARCHIVE_READ_FAILED") from None
            if record_count != EXPECTED_RECORDS[split]:
                raise PiiScanError("RECORD_COUNT_DRIFT")

    result = {
        "dataset_id": DATASET_ID,
        "execution_id": EXECUTION_ID,
        "scan_scope": {
            "components": ["sftdata", "sftlabel"],
            "splits": ["training", "validation"],
            "fields": sorted(ALLOWED_OUTPUT_FIELD_PATHS),
        },
        "summary": dict(summary),
        "components": components,
        "splits": splits,
        "fields": fields,
        "candidate_types": {key: {"occurrences": type_occurrences[key], "affected_records": type_records[key]} for key in CANDIDATE_TYPES},
        "risk_levels": dict(risk_levels),
        "candidate_groups": dict(groups),
        "combinations": dict(combinations),
        "safety": {
            "raw_value_output": False, "raw_context_output": False,
            "stable_record_identifier_output": False, "stdout_leak": False,
            "stderr_leak": False, "exception_leak": False, "logging_leak": False,
        },
        "full_scan_count": 1,
        "dataset_candidate_status": "review_required_before_next_scan" if risk_levels["critical"] else "pending_policy_decision",
        "status": "completed_candidates_detected" if summary["records_with_any_candidate"] else "completed_no_candidates_detected",
        "execution_allowed": False,
    }
    guarded = guard_safe_output(result, [])
    if guarded is not None:
        raise PiiScanError(guarded["error_code"])
    return result


def scan_aihub_71748_pii(package_root: str | Path) -> dict[str, Any]:
    """Run the single approved full scan without retry."""

    root = Path(package_root)
    if not root.is_dir():
        return {"status": "blocked_runtime_failure", "error_code": "PACKAGE_ROOT_MISSING", "full_scan_count": 0, "execution_allowed": False}
    try:
        return _scan_once(root)
    except PiiScanError as exc:
        return {"status": "blocked_runtime_failure", "error_code": exc.code, "full_scan_count": 1, "execution_allowed": False}
