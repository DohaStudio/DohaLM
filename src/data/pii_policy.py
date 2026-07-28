"""Pure, payload-free policy decisions for PII candidate metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


DIRECT_IDENTIFIER_TYPES = frozenset({
    "resident_id_like",
    "foreign_registration_id_like",
    "passport_like",
    "driver_license_like",
    "phone",
    "email",
    "account_number_like",
    "card_number_like",
    "detailed_address",
    "address",
    "vehicle_number_like",
    "patient_number_like",
    "employee_number_like",
    "student_number_like",
    "ip_address",
    "url",
    "social_handle",
})
QUASI_IDENTIFIER_TYPES = frozenset({
    "person_name_candidate",
    "birth_date",
    "age",
    "gender",
    "region",
    "school",
    "company",
    "department",
    "job_title",
    "family_relation",
    "family_relation_candidate",
    "organization_role_combination",
    "postal_code",
})
SENSITIVE_TOPIC_TYPES = frozenset({
    "medical",
    "medical_sensitive_candidate",
    "mental_health",
    "mental_health_candidate",
    "legal",
    "legal_sensitive_candidate",
    "financial",
    "financial_sensitive_candidate",
    "religion",
    "religion_candidate",
    "political",
    "political_candidate",
    "disability",
    "sexual_orientation",
    "labor_union",
    "criminal",
})
LINKED_SENSITIVE_TYPES = frozenset({
    "direct_identifier_plus_sensitive_topic",
    "person_candidate_plus_sensitive_topic",
    "address_plus_sensitive_topic",
    "birth_date_plus_sensitive_topic",
    "organization_role_plus_sensitive_topic",
})
VALIDATED_HIGH_RISK_TYPES = frozenset({"resident_id_like", "foreign_registration_id_like", "card_number_like"})
KNOWN_DETECTOR_TYPES = (
    DIRECT_IDENTIFIER_TYPES | QUASI_IDENTIFIER_TYPES | SENSITIVE_TOPIC_TYPES | LINKED_SENSITIVE_TYPES
)

FIELD_POLICIES = {
    "$.sftdata.question": {"role": "user_instruction", "pii_tolerance": "strict"},
    "$.sftlabel.question": {
        "role": "duplicated_or_related_question_component",
        "pii_tolerance": "strict",
    },
    "$.sftlabel.answer.contents": {"role": "model_target", "pii_tolerance": "very_strict"},
}
CONFIDENCE_LEVELS = frozenset({"unspecified", "low", "medium", "high", "validated"})


class PiiPolicyError(RuntimeError):
    """Fail-closed policy input error with a fixed, non-sensitive code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PiiPolicyDecision:
    policy_label: str
    policy_risk: str
    action_candidate: str
    reason_code: str
    field_role: str
    pii_tolerance: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _decision(
    label: str,
    risk: str,
    action: str,
    reason: str,
    field_path: str,
) -> PiiPolicyDecision:
    field = FIELD_POLICIES[field_path]
    return PiiPolicyDecision(label, risk, action, reason, field["role"], field["pii_tolerance"])


def evaluate_pii_policy(
    detector_types: Iterable[str],
    *,
    field_path: str,
    confidence: str = "unspecified",
    combined_detector_types: Iterable[str] = (),
    occurrence_count: int = 1,
) -> PiiPolicyDecision:
    """Classify detector metadata without accepting or returning source text."""

    if field_path not in FIELD_POLICIES:
        raise PiiPolicyError("UNKNOWN_FIELD_PATH")
    if confidence not in CONFIDENCE_LEVELS:
        raise PiiPolicyError("UNKNOWN_CONFIDENCE")
    if isinstance(occurrence_count, bool) or not isinstance(occurrence_count, int) or occurrence_count < 0:
        raise PiiPolicyError("INVALID_OCCURRENCE_COUNT")

    types = frozenset(detector_types)
    combined = frozenset(combined_detector_types)
    if not all(isinstance(value, str) for value in types | combined):
        raise PiiPolicyError("UNKNOWN_DETECTOR_TYPE")
    unknown = (types | combined) - KNOWN_DETECTOR_TYPES
    if unknown:
        raise PiiPolicyError("UNKNOWN_DETECTOR_TYPE")

    direct = types & DIRECT_IDENTIFIER_TYPES
    quasi = types & QUASI_IDENTIFIER_TYPES
    sensitive = types & SENSITIVE_TOPIC_TYPES
    linked = (types | combined) & LINKED_SENSITIVE_TYPES

    if linked or (direct and sensitive):
        return _decision(
            "PII_BLOCKED", "block_candidate", "block_candidate",
            "DIRECT_IDENTIFIER_WITH_SENSITIVE_TOPIC" if direct and sensitive else "LINKED_SENSITIVE_CANDIDATE",
            field_path,
        )
    if direct & VALIDATED_HIGH_RISK_TYPES:
        return _decision(
            "PII_BLOCKED", "block_candidate", "block_candidate", "VALIDATED_HIGH_RISK_IDENTIFIER", field_path
        )
    if len(direct) >= 2:
        return _decision(
            "PII_BLOCKED", "block_candidate", "block_candidate", "MULTIPLE_DIRECT_IDENTIFIERS", field_path
        )
    if direct and quasi:
        return _decision(
            "PII_EXCLUDE_CANDIDATE",
            "restricted_candidate",
            "exclude_candidate",
            "DIRECT_IDENTIFIER_WITH_QUASI_IDENTIFIER",
            field_path,
        )
    if direct:
        return _decision(
            "PII_REVIEW_REQUIRED", "review_candidate", "review", "SINGLE_DIRECT_IDENTIFIER", field_path
        )
    if len(quasi) >= 2:
        return _decision(
            "PII_REVIEW_REQUIRED", "review_candidate", "review", "MULTIPLE_QUASI_IDENTIFIERS", field_path
        )
    if quasi:
        return _decision(
            "PII_UNRESOLVED", "informational", "retain", "SINGLE_QUASI_IDENTIFIER", field_path
        )
    if sensitive:
        return _decision(
            "PII_TOPIC_ONLY", "informational", "retain", "SENSITIVE_TOPIC_ONLY", field_path
        )
    return _decision(
        "PII_CLEAR_BY_RULE", "informational", "retain", "NO_CANDIDATE_DETECTED", field_path
    )
