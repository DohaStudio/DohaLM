import pytest

from src.data.pii_policy import PiiPolicyError, evaluate_pii_policy


QUESTION = "$.sftdata.question"
ANSWER = "$.sftlabel.answer.contents"


@pytest.mark.parametrize(
    "candidate",
    ["medical_sensitive_candidate", "religion_candidate", "legal_sensitive_candidate"],
)
def test_sensitive_topic_alone_is_informational(candidate):
    result = evaluate_pii_policy({candidate}, field_path=QUESTION)
    assert result.policy_label == "PII_TOPIC_ONLY"
    assert result.policy_risk == "informational"
    assert result.action_candidate == "retain"


def test_name_candidate_alone_is_not_blocked():
    result = evaluate_pii_policy({"person_name_candidate"}, field_path=QUESTION)
    assert result.policy_label == "PII_UNRESOLVED"
    assert result.policy_risk == "informational"


@pytest.mark.parametrize("candidate", ["phone", "email"])
def test_single_direct_identifier_requires_review(candidate):
    result = evaluate_pii_policy({candidate}, field_path=QUESTION)
    assert result.policy_label == "PII_REVIEW_REQUIRED"
    assert result.policy_risk == "review_candidate"


def test_validated_high_risk_identifier_is_blocked():
    result = evaluate_pii_policy({"resident_id_like"}, field_path=ANSWER, confidence="validated")
    assert result.policy_label == "PII_BLOCKED"
    assert result.reason_code == "VALIDATED_HIGH_RISK_IDENTIFIER"


@pytest.mark.parametrize(
    "candidates",
    [
        {"medical_sensitive_candidate", "phone"},
        {"financial_sensitive_candidate", "card_number_like"},
    ],
)
def test_direct_identifier_with_sensitive_topic_is_blocked(candidates):
    result = evaluate_pii_policy(candidates, field_path=ANSWER)
    assert result.policy_label == "PII_BLOCKED"
    assert result.policy_risk == "block_candidate"


def test_family_and_name_require_review():
    result = evaluate_pii_policy(
        {"family_relation_candidate", "person_name_candidate"}, field_path=QUESTION
    )
    assert result.policy_label == "PII_REVIEW_REQUIRED"


def test_generic_region_is_not_promoted_to_detailed_address():
    result = evaluate_pii_policy({"region"}, field_path=QUESTION)
    assert result.policy_label == "PII_UNRESOLVED"
    assert result.policy_risk != "block_candidate"


def test_public_institution_address_is_not_automatically_personal_address():
    result = evaluate_pii_policy({"address", "company"}, field_path=QUESTION)
    assert result.policy_label == "PII_EXCLUDE_CANDIDATE"
    assert result.policy_risk == "restricted_candidate"
    assert result.action_candidate != "block_candidate"


def test_multiple_sensitive_topics_do_not_promote_to_direct_identifier():
    result = evaluate_pii_policy(
        {"medical_sensitive_candidate", "religion_candidate", "legal_sensitive_candidate"},
        field_path=ANSWER,
    )
    assert result.policy_label == "PII_TOPIC_ONLY"
    assert result.reason_code == "SENSITIVE_TOPIC_ONLY"


def test_linked_sensitive_candidate_is_blocked():
    result = evaluate_pii_policy(
        set(),
        combined_detector_types={"person_candidate_plus_sensitive_topic"},
        field_path=ANSWER,
    )
    assert result.policy_label == "PII_BLOCKED"
    assert result.reason_code == "LINKED_SENSITIVE_CANDIDATE"


def test_answer_field_uses_very_strict_tolerance():
    result = evaluate_pii_policy({"phone"}, field_path=ANSWER)
    assert result.field_role == "model_target"
    assert result.pii_tolerance == "very_strict"


@pytest.mark.parametrize(
    ("kwargs", "error_code"),
    [
        ({"detector_types": {"unknown_detector"}, "field_path": QUESTION}, "UNKNOWN_DETECTOR_TYPE"),
        ({"detector_types": set(), "field_path": "$.dynamic"}, "UNKNOWN_FIELD_PATH"),
        ({"detector_types": set(), "field_path": QUESTION, "confidence": "certain"}, "UNKNOWN_CONFIDENCE"),
        ({"detector_types": set(), "field_path": QUESTION, "occurrence_count": -1}, "INVALID_OCCURRENCE_COUNT"),
    ],
)
def test_unknown_or_invalid_policy_input_fails_closed(kwargs, error_code):
    with pytest.raises(PiiPolicyError, match=error_code) as error:
        evaluate_pii_policy(**kwargs)
    assert error.value.code == error_code


def test_no_candidate_is_clear_by_rule_not_dataset_approval():
    result = evaluate_pii_policy(set(), field_path=QUESTION, occurrence_count=0)
    assert result.policy_label == "PII_CLEAR_BY_RULE"
    assert result.action_candidate == "retain"
