"""원문 값 없이 수동 schema·PII 검토 bundle을 구성한다."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping

from .analyzer import LABEL_FIELD_NAMES, PII_FIELD_NAMES, TEXT_FIELD_NAMES
from .safe_sampler import SamplerError, _sha256_text
from .zip_json_record_sampler import ALLOWED_SCHEMA_KEYS, analyze_record


PII_SIGNAL_GROUPS = {
    "direct_identifier_field_name": {
        "name", "person", "resident_number", "id_number", "birth", "이름", "성명", "주민번호", "생년월일",
    },
    "contact_field_name": {"phone", "telephone", "email", "전화번호", "이메일"},
    "address_field_name": {"address", "주소"},
    "account_user_id_field_name": {"account", "user_id", "userid", "username", "계정"},
    "counseling_health_field_name": {
        "hospital", "diagnosis", "counseling", "병원", "진단", "상담", "health", "medical",
    },
}


def validate_preview_request(*, requested: bool, approved: bool = False) -> None:
    if requested or approved:
        raise SamplerError("수동 preview 생성은 이번 구현 범위에서 비활성화돼 있습니다.")


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _category(key: str) -> str:
    normalized = key.casefold()
    if normalized in PII_FIELD_NAMES or any(normalized in names for names in PII_SIGNAL_GROUPS.values()):
        return "pii_review_required"
    if normalized == "source":
        return "source"
    if normalized == "metadata":
        return "metadata"
    if normalized in {"label", "role"} or normalized in LABEL_FIELD_NAMES:
        return "label"
    if normalized in {"text", "content", "instruction", "input", "output", "response", "question", "answer"}:
        return "likely_text"
    if normalized in TEXT_FIELD_NAMES:
        return "possible_text"
    return "excluded"


def _pii_groups(key: str) -> list[str]:
    normalized = key.casefold()
    return sorted(name for name, values in PII_SIGNAL_GROUPS.items() if normalized in values)


def analyze_review_record(value: Any) -> dict[str, Any]:
    """선택 record를 field 단위 비노출 통계로 변환한다."""

    base = analyze_record(value)
    fields: dict[str, dict[str, Any]] = {}
    stack: list[tuple[Any, int, str | None]] = [(value, 0, None)]
    while stack:
        current, depth, parent_key = stack.pop()
        if isinstance(current, dict):
            for raw_key, child in reversed(list(current.items())):
                key = str(raw_key)
                normalized = key.casefold()
                key_hash = _sha256_text(key)
                row = fields.setdefault(key_hash, {
                    "field_name_hash": key_hash,
                    "allowed_display_name": normalized if normalized in ALLOWED_SCHEMA_KEYS else None,
                    "observed_value_types": Counter(),
                    "occurrence_count": 0,
                    "string_lengths": [],
                    "nested_depth": 0,
                    "candidate_category": _category(key),
                    "pii_signal_groups": set(),
                })
                row["observed_value_types"][_value_type(child)] += 1
                row["occurrence_count"] += 1
                row["nested_depth"] = max(row["nested_depth"], depth + 1)
                if isinstance(child, str):
                    row["string_lengths"].append(len(child))
                row["pii_signal_groups"].update(_pii_groups(key))
                stack.append((child, depth + 1, key))
        elif isinstance(current, list):
            stack.extend((item, depth + 1, parent_key) for item in reversed(current))

    field_rows = []
    for key_hash, row in sorted(fields.items()):
        lengths = row["string_lengths"]
        field_rows.append({
            "field_name_hash": key_hash,
            "allowed_display_name": row["allowed_display_name"],
            "observed_value_types": dict(sorted(row["observed_value_types"].items())),
            "occurrence_count": row["occurrence_count"],
            "string_length_min": min(lengths) if lengths else None,
            "string_length_max": max(lengths) if lengths else None,
            "string_length_mean": statistics.fmean(lengths) if lengths else None,
            "string_length_count": len(lengths),
            "string_length_sum": sum(lengths),
            "nested_depth": row["nested_depth"],
            "candidate_category": row["candidate_category"],
            "pii_signal_groups": sorted(row["pii_signal_groups"]),
        })
    return {
        "record_type": base["record_type"],
        "schema_signature": base["schema_signature"],
        "fields": field_rows,
    }


def build_schema_review_bundle(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    signature_ids = {
        signature: "schema-" + signature.removeprefix("sha256:")[:12]
        for signature in sorted({row["schema_signature"] for row in rows})
    }
    signature_counts = Counter(row["schema_signature"] for row in rows)
    fields: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "allowed_display_name": None,
        "observed_value_types": Counter(),
        "record_ids": set(),
        "string_length_minima": [],
        "string_length_maxima": [],
        "string_length_count": 0,
        "string_length_sum": 0,
        "nested_depth": 0,
        "candidate_categories": Counter(),
        "schema_signature_ids": set(),
        "strata_presence": set(),
        "pii_signal_groups": set(),
    })
    for record in rows:
        record_id = (record["entry_name_hash"], record["record_index"])
        signature_id = signature_ids[record["schema_signature"]]
        for field in record["fields"]:
            aggregate = fields[field["field_name_hash"]]
            aggregate["allowed_display_name"] = field["allowed_display_name"]
            aggregate["observed_value_types"].update(field["observed_value_types"])
            aggregate["record_ids"].add(record_id)
            if field["string_length_min"] is not None:
                aggregate["string_length_minima"].append(field["string_length_min"])
                aggregate["string_length_maxima"].append(field["string_length_max"])
                aggregate["string_length_count"] += field["string_length_count"]
                aggregate["string_length_sum"] += field["string_length_sum"]
            aggregate["nested_depth"] = max(aggregate["nested_depth"], field["nested_depth"])
            aggregate["candidate_categories"][field["candidate_category"]] += 1
            aggregate["schema_signature_ids"].add(signature_id)
            aggregate["strata_presence"].add(record["record_stratum"])
            aggregate["pii_signal_groups"].update(field["pii_signal_groups"])

    field_rows = []
    pii_group_counts: Counter[str] = Counter()
    for field_hash, value in sorted(fields.items()):
        presence = len(value["record_ids"])
        category = value["candidate_categories"].most_common(1)[0][0]
        minima = value["string_length_minima"]
        maxima = value["string_length_maxima"]
        for group in value["pii_signal_groups"]:
            pii_group_counts[group] += presence
        manual_status = "review_required" if category in {
            "likely_text", "possible_text", "metadata", "source", "pii_review_required",
        } else "not_reviewed"
        field_rows.append({
            "field_name_hash": field_hash,
            "allowed_display_name": value["allowed_display_name"],
            "observed_value_types": dict(sorted(value["observed_value_types"].items())),
            "record_presence_count": presence,
            "record_presence_ratio": presence / len(rows) if rows else 0.0,
            "string_length_min": min(minima) if minima else None,
            "string_length_max": max(maxima) if maxima else None,
            "string_length_mean": (
                value["string_length_sum"] / value["string_length_count"]
                if value["string_length_count"] else None
            ),
            "nested_depth": value["nested_depth"],
            "candidate_category": category,
            "schema_signature_ids": sorted(value["schema_signature_ids"]),
            "strata_presence": sorted(value["strata_presence"]),
            "manual_review_status": manual_status,
            "manual_review_reason": "limited_structure_observation_requires_human_review",
        })

    checklist = []
    checklist_names = [
        "direct_identifier_field_name", "contact_field_name", "address_field_name",
        "account_user_id_field_name", "counseling_health_field_name",
    ]
    for name in checklist_names:
        count = pii_group_counts[name]
        checklist.append({
            "check": name,
            "status": "review_required" if count else "no_field_name_signal",
            "field_presence_count": count,
            "note": "no_field_name_signal_does_not_mean_pii_absent",
        })
    text_present = any(row["candidate_category"] in {"likely_text", "possible_text"} for row in field_rows)
    metadata_present = any(row["candidate_category"] in {"metadata", "source"} for row in field_rows)
    checklist.extend([
        {
            "check": "free_text_may_contain_pii",
            "status": "review_required" if text_present else "not_reviewed",
            "note": "values_not_inspected_by_automatic_contract",
        },
        {
            "check": "metadata_source_identifier_possible",
            "status": "review_required" if metadata_present else "not_reviewed",
            "note": "values_not_inspected_by_automatic_contract",
        },
        {"check": "deidentification_description_exists", "status": "not_reviewed"},
        {"check": "official_description_schema_match", "status": "not_reviewed"},
    ])
    return {
        "schema_signatures": [
            {
                "schema_signature_id": signature_ids[signature],
                "schema_signature_hash": signature,
                "record_count": count,
            }
            for signature, count in sorted(signature_counts.items())
        ],
        "field_review_manifest": field_rows,
        "pii_review_checklist": checklist,
        "selected_record_count": len(rows),
        "schema_confirmed": False,
        "pii_absence_confirmed": False,
    }
