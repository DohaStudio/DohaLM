"""Pure quality checks for the meaning-preserving v0.3 short-answer Dataset."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping

from src.data.v02_sidecar import completion_metrics, repetition_metrics


_SENTENCE = re.compile(r"[^.!?。！？\n]+(?:[.!?。！？]+|$)")
_NUMBER = re.compile(
    r"(?<![\w])[-+]?\d+(?:[.,]\d+)*(?:%|년|월|일|개|명|회|배|kg|km|m|원)?",
    re.IGNORECASE,
)
_ENTITY = re.compile(
    r"(?:[A-Z][A-Za-z0-9._-]{1,}|[가-힣A-Za-z0-9]+(?:대학교|연구원|위원회|공사|협회|재단|정부|법|모델))"
)
_NEGATION = re.compile(r"(?:않|못|없|아니|금지|불가|제외)")


def normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).replace("\r", "\n").split())


def split_sentences(value: str) -> list[str]:
    return [
        normalize_text(item.group(0))
        for item in _SENTENCE.finditer(value)
        if normalize_text(item.group(0))
    ]


def extract_numbers(value: str) -> tuple[str, ...]:
    return tuple(_NUMBER.findall(normalize_text(value)))


def extract_entities(value: str) -> tuple[str, ...]:
    return tuple(sorted(set(_ENTITY.findall(normalize_text(value)))))


def ngram_excess_ratio(value: str, size: int) -> float:
    compact = normalize_text(value).replace(" ", "")
    if len(compact) < size:
        return 0.0
    grams = [compact[index : index + size] for index in range(len(compact) - size + 1)]
    counts = Counter(grams)
    excess = sum(count - 1 for count in counts.values())
    return excess / len(grams)


def select_extractive_variant(
    instruction: str,
    source_answer: str,
    *,
    token_count: Callable[[str], int],
    minimum_tokens: int,
    maximum_tokens: int,
) -> str | None:
    """Select ordered source sentences; never truncate or synthesize text."""

    sentences = split_sentences(source_answer)
    if not sentences:
        return None
    question_terms = set(
        re.findall(r"[가-힣A-Za-z0-9]{2,}", normalize_text(instruction))
    )
    scored: list[tuple[float, int]] = []
    for index, sentence in enumerate(sentences):
        terms = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", sentence))
        score = float(len(question_terms & terms) * 4)
        score += 3.0 if index == len(sentences) - 1 else 0.0
        score += 1.0 if index == 0 else 0.0
        score += min(len(extract_numbers(sentence)), 3) * 2.0
        score += min(len(extract_entities(sentence)), 3) * 1.5
        scored.append((score, index))

    selected: set[int] = set()
    for _, index in sorted(scored, key=lambda item: (-item[0], item[1])):
        proposal = " ".join(sentences[item] for item in sorted((*selected, index)))
        if token_count(proposal) <= maximum_tokens:
            selected.add(index)
        current = " ".join(sentences[item] for item in sorted(selected))
        if token_count(current) >= minimum_tokens:
            break
    candidate = " ".join(sentences[item] for item in sorted(selected))
    count = token_count(candidate) if candidate else 0
    if not minimum_tokens <= count <= maximum_tokens:
        return None
    return candidate


def assess_candidate(
    *,
    source_answer: str,
    candidate: str,
    source_tokens: int,
    candidate_tokens: int,
    semantic_score: float,
    semantic_threshold: float,
    generation_method: str,
) -> dict[str, object]:
    source = normalize_text(source_answer)
    generated = normalize_text(candidate)
    source_numbers = set(extract_numbers(source))
    candidate_numbers = set(extract_numbers(generated))
    source_entities = set(extract_entities(source))
    candidate_entities = set(extract_entities(generated))
    completion_score, complete, completion_signals = completion_metrics(generated)
    repetition_score, strong_repeat, repetition_signals = repetition_metrics(
        generated, near_duplicate=False
    )
    four_gram = ngram_excess_ratio(generated, 4)
    five_gram = ngram_excess_ratio(generated, 5)
    exact_extractive = all(
        sentence in source for sentence in split_sentences(generated)
    )
    numeric_passed = candidate_numbers <= source_numbers
    entity_passed = candidate_entities <= source_entities
    contradiction = (
        bool(_NEGATION.search(source)) != bool(_NEGATION.search(generated))
    ) and not exact_extractive
    new_fact = generation_method != "extractive" or not exact_extractive
    reasons: list[str] = []
    if not 80 <= candidate_tokens <= 320:
        reasons.append("token_length_outside_supported_range")
    if not complete or completion_score != 1.0:
        reasons.append("incomplete")
    if strong_repeat:
        reasons.append("strong_repetition")
    if semantic_score < semantic_threshold:
        reasons.append("semantic_threshold")
    if not numeric_passed:
        reasons.append("numeric_mismatch")
    if not entity_passed:
        reasons.append("entity_mismatch")
    if contradiction:
        reasons.append("contradiction")
    if new_fact:
        reasons.append("new_fact_risk")
    if not 0.15 <= candidate_tokens / source_tokens <= 0.60:
        reasons.append("compression_ratio_review")
    review_required = bool(reasons) or generation_method == "constrained_abstractive"
    accepted = not review_required and 80 <= candidate_tokens <= 320
    variant_type = "short" if candidate_tokens <= 180 else "medium"
    return {
        "variant_type": variant_type,
        "completion_score": completion_score,
        "repetition_score": repetition_score,
        "semantic_preservation_score": round(float(semantic_score), 8),
        "entity_preservation_score": 1.0 if entity_passed else 0.0,
        "numeric_preservation_score": 1.0 if numeric_passed else 0.0,
        "compression_ratio": candidate_tokens / source_tokens,
        "contradiction_detected": contradiction,
        "new_fact_detected": new_fact,
        "strong_repeat_candidate": strong_repeat,
        "four_gram_excess_ratio": four_gram,
        "five_gram_excess_ratio": five_gram,
        "completion_signals": completion_signals,
        "repetition_signals": repetition_signals,
        "review_required": review_required,
        "accepted": accepted,
        "rejection_reasons": sorted(set(reasons)),
    }


def validate_no_raw_text(record: Mapping[str, object]) -> None:
    forbidden = {
        "instruction",
        "input",
        "output",
        "system",
        "question",
        "answer",
        "text",
        "token_ids",
    }
    if forbidden & set(record):
        raise ValueError("RAW_TEXT_FIELD_FORBIDDEN")
