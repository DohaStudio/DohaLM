"""Deterministic, synthetic-only EOS-DIAG-R4 analysis backend.

The backend consumes caller-provided numeric observations.  It never imports a
model framework, opens model/tokenizer/prompt artifacts, or performs generation.
Only opaque identifiers, token integers, hashes, and aggregate values are
accepted and emitted.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .eos_diagnostic_artifacts import diagnostic_fingerprint

TRACE_SCHEMA_VERSION = 4
OBSERVATION_SCHEMA_VERSION = 4
RESULT_SCHEMA_VERSION = 4
LENGTHS = (16, 32, 64, 128)
EVIDENCE_STATUSES = frozenset(
    {
        "complete",
        "complete_with_limitations",
        "insufficient_evidence",
        "incompatible_input",
        "blocked",
        "schema_only",
    }
)
TERMINATION_TYPES = frozenset({"eos", "max_length", "cancelled", "error", "incomplete"})
DECODING_ROLES = frozenset(
    {"pure_greedy", "sampling", "repetition_penalty", "no_repeat_ngram"}
)
EOS_DIAGNOSTIC_BACKEND_ERROR_CODES = frozenset(
    {
        "EOS_DIAG_TRACE_INVALID",
        "EOS_DIAG_OBSERVATION_INVALID",
        "EOS_DIAG_PAIRING_INVALID",
        "EOS_DIAG_LOOP_CONFIG_INVALID",
        "EOS_DIAG_LENGTH_MATRIX_INVALID",
        "EOS_DIAG_ABLATION_INVALID",
        "EOS_DIAG_BUDGET_PROXY_INVALID",
        "EOS_DIAG_INSUFFICIENT_EVIDENCE",
        "EOS_DIAG_INPUT_INCOMPATIBLE",
        "EOS_DIAG_ARTIFACT_PAYLOAD_INVALID",
        "EOS_DIAG_JSONL_INVALID",
    }
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}\Z")
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}\Z")
_FORBIDDEN_KEYS = frozenset(
    {
        "prompt",
        "prompt_text",
        "generated_text",
        "text",
        "token_string",
        "tokens",
        "token_sequence",
        "record_id",
        "source_record_id",
        "path",
        "absolute_path",
        "secret",
    }
)


class EOSDiagnosticBackendError(RuntimeError):
    """Fail-closed backend error exposing only a stable safe code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fail(code: str) -> None:
    raise EOSDiagnosticBackendError(code)


def _strict(value: object, fields: Sequence[str], code: str) -> Mapping[str, Any]:
    if type(value) is not dict or set(value) != set(fields):
        _fail(code)
    if set(value) & _FORBIDDEN_KEYS:
        _fail(code)
    return value


def _text(value: object, code: str) -> str:
    if type(value) is not str or not _IDENTIFIER.fullmatch(value):
        _fail(code)
    return value


def _integer(value: object, code: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(code)
    return value


def _number(value: object, code: str, *, probability: bool = False) -> float:
    if type(value) not in {int, float}:
        _fail(code)
    result = float(value)
    if not math.isfinite(result) or (probability and not 0.0 <= result <= 1.0):
        _fail(code)
    return result


def _boolean(value: object, code: str) -> bool:
    if type(value) is not bool:
        _fail(code)
    return value


def _fingerprint(value: object, code: str) -> str:
    if type(value) is not str or not _FINGERPRINT.fullmatch(value):
        _fail(code)
    return value


def _freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _mean(values: Sequence[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def _rate(count: int, total: int) -> float:
    return 0.0 if total == 0 else count / total


def _bucket_step(step: int) -> str:
    if step < 16:
        return "0-15"
    if step < 32:
        return "16-31"
    if step < 64:
        return "32-63"
    return "64-plus"


def _bucket_distance(distance: int) -> str:
    if distance == 0:
        return "0"
    if distance <= 2:
        return "1-2"
    if distance <= 7:
        return "3-7"
    return "8-plus"


@dataclass(frozen=True)
class GeneratedStep:
    step_index: int
    selected_token_id: int
    eos_logit: float
    eos_probability: float
    eos_rank: int
    top_competitor_token_ids: tuple[int, ...]
    top_competitor_logits: tuple[float, ...]
    selected_token_probability: float
    unique_token_ratio_so_far: float
    repeated_ngram_hashes: tuple[str, ...]
    boundary_distance: int | None
    is_eos_selected: bool

    @classmethod
    def from_mapping(cls, value: object) -> GeneratedStep:
        code = "EOS_DIAG_TRACE_INVALID"
        item = _strict(
            value,
            (
                "step_index",
                "selected_token_id",
                "eos_logit",
                "eos_probability",
                "eos_rank",
                "top_competitor_token_ids",
                "top_competitor_logits",
                "selected_token_probability",
                "unique_token_ratio_so_far",
                "repeated_ngram_hashes",
                "boundary_distance",
                "is_eos_selected",
            ),
            code,
        )
        competitors = item["top_competitor_token_ids"]
        logits = item["top_competitor_logits"]
        hashes = item["repeated_ngram_hashes"]
        if (
            type(competitors) is not list
            or type(logits) is not list
            or type(hashes) is not list
        ):
            _fail(code)
        competitor_ids = tuple(_integer(token, code) for token in competitors)
        competitor_logits = tuple(_number(logit, code) for logit in logits)
        if len(competitor_ids) != len(competitor_logits) or len(
            set(competitor_ids)
        ) != len(competitor_ids):
            _fail(code)
        selected = _integer(item["selected_token_id"], code)
        if selected in competitor_ids:
            _fail(code)
        repeated = tuple(_fingerprint(value, code) for value in hashes)
        if tuple(sorted(set(repeated))) != repeated:
            _fail(code)
        distance = item["boundary_distance"]
        if distance is not None:
            distance = _integer(distance, code)
        return cls(
            step_index=_integer(item["step_index"], code),
            selected_token_id=selected,
            eos_logit=_number(item["eos_logit"], code),
            eos_probability=_number(item["eos_probability"], code, probability=True),
            eos_rank=_integer(item["eos_rank"], code, minimum=1),
            top_competitor_token_ids=competitor_ids,
            top_competitor_logits=competitor_logits,
            selected_token_probability=_number(
                item["selected_token_probability"], code, probability=True
            ),
            unique_token_ratio_so_far=_number(
                item["unique_token_ratio_so_far"], code, probability=True
            ),
            repeated_ngram_hashes=repeated,
            boundary_distance=distance,
            is_eos_selected=_boolean(item["is_eos_selected"], code),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "selected_token_id": self.selected_token_id,
            "eos_logit": self.eos_logit,
            "eos_probability": self.eos_probability,
            "eos_rank": self.eos_rank,
            "top_competitor_token_ids": list(self.top_competitor_token_ids),
            "top_competitor_logits": list(self.top_competitor_logits),
            "selected_token_probability": self.selected_token_probability,
            "unique_token_ratio_so_far": self.unique_token_ratio_so_far,
            "repeated_ngram_hashes": list(self.repeated_ngram_hashes),
            "boundary_distance": self.boundary_distance,
            "is_eos_selected": self.is_eos_selected,
        }


@dataclass(frozen=True)
class SyntheticGenerationTrace:
    schema_version: int
    diagnostic_run_id: str
    opaque_prompt_id: str
    prompt_category: str
    prompt_length_bucket: str
    context_class: str
    generation_profile_id: str
    max_new_tokens: int
    decoding_role: str
    seed: int
    eos_token_id: int
    generated_steps: tuple[GeneratedStep, ...]
    termination_type: str
    prefix_derived: bool
    source_max_new_tokens: int
    trace_fingerprint: str

    @classmethod
    def from_mapping(cls, value: object) -> SyntheticGenerationTrace:
        code = "EOS_DIAG_TRACE_INVALID"
        item = _strict(
            value,
            (
                "schema_version",
                "diagnostic_run_id",
                "opaque_prompt_id",
                "prompt_category",
                "prompt_length_bucket",
                "context_class",
                "generation_profile_id",
                "max_new_tokens",
                "decoding_role",
                "seed",
                "eos_token_id",
                "generated_steps",
                "termination_type",
                "prefix_derived",
                "source_max_new_tokens",
                "trace_fingerprint",
            ),
            code,
        )
        if item["schema_version"] != TRACE_SCHEMA_VERSION:
            _fail(code)
        raw_steps = item["generated_steps"]
        if type(raw_steps) is not list:
            _fail(code)
        steps = tuple(GeneratedStep.from_mapping(step) for step in raw_steps)
        if tuple(step.step_index for step in steps) != tuple(range(len(steps))):
            _fail(code)
        eos_id = _integer(item["eos_token_id"], code)
        for step in steps:
            if step.is_eos_selected != (step.selected_token_id == eos_id):
                _fail(code)
        termination = item["termination_type"]
        if termination not in TERMINATION_TYPES:
            _fail(code)
        eos_steps = [step.step_index for step in steps if step.is_eos_selected]
        if (termination == "eos") != bool(eos_steps) or (
            eos_steps and eos_steps[-1] != len(steps) - 1
        ):
            _fail(code)
        max_new_tokens = _integer(item["max_new_tokens"], code, minimum=1)
        source_length = _integer(item["source_max_new_tokens"], code, minimum=1)
        prefix_derived = _boolean(item["prefix_derived"], code)
        if (
            len(steps) > max_new_tokens
            or (
                prefix_derived
                and (source_length != 128 or max_new_tokens not in {16, 32, 64})
            )
            or (not prefix_derived and source_length != max_new_tokens)
        ):
            _fail(code)
        if termination == "max_length" and len(steps) != max_new_tokens:
            _fail(code)
        role = item["decoding_role"]
        if role not in DECODING_ROLES:
            _fail(code)
        semantic = dict(item)
        supplied = _fingerprint(semantic.pop("trace_fingerprint"), code)
        if diagnostic_fingerprint(semantic) != supplied:
            _fail(code)
        return cls(
            schema_version=TRACE_SCHEMA_VERSION,
            diagnostic_run_id=_text(item["diagnostic_run_id"], code),
            opaque_prompt_id=_text(item["opaque_prompt_id"], code),
            prompt_category=_text(item["prompt_category"], code),
            prompt_length_bucket=_text(item["prompt_length_bucket"], code),
            context_class=_text(item["context_class"], code),
            generation_profile_id=_text(item["generation_profile_id"], code),
            max_new_tokens=max_new_tokens,
            decoding_role=role,
            seed=_integer(item["seed"], code),
            eos_token_id=eos_id,
            generated_steps=steps,
            termination_type=termination,
            prefix_derived=prefix_derived,
            source_max_new_tokens=source_length,
            trace_fingerprint=supplied,
        )


@dataclass(frozen=True)
class TeacherForcedObservation:
    opaque_prompt_id: str
    category: str
    target_position: int
    pairing_key: str
    eos_target: bool
    eos_logit: float
    eos_probability: float
    eos_rank: int
    top_competitor_token_ids: tuple[int, ...]
    sequence_boundary_distance: int | None
    packed_sequence: bool
    observation_fingerprint: str

    @classmethod
    def from_mapping(cls, value: object) -> TeacherForcedObservation:
        code = "EOS_DIAG_OBSERVATION_INVALID"
        item = _strict(
            value,
            (
                "opaque_prompt_id",
                "category",
                "target_position",
                "pairing_key",
                "eos_target",
                "eos_logit",
                "eos_probability",
                "eos_rank",
                "top_competitor_token_ids",
                "sequence_boundary_distance",
                "packed_sequence",
                "observation_fingerprint",
            ),
            code,
        )
        competitors = item["top_competitor_token_ids"]
        if type(competitors) is not list:
            _fail(code)
        competitor_ids = tuple(_integer(token, code) for token in competitors)
        if len(set(competitor_ids)) != len(competitor_ids):
            _fail(code)
        distance = item["sequence_boundary_distance"]
        if distance is not None:
            distance = _integer(distance, code)
        semantic = dict(item)
        supplied = _fingerprint(semantic.pop("observation_fingerprint"), code)
        if diagnostic_fingerprint(semantic) != supplied:
            _fail(code)
        prompt_id = _text(item["opaque_prompt_id"], code)
        target_position = _integer(item["target_position"], code)
        pairing_key = _text(item["pairing_key"], code)
        if pairing_key != f"{prompt_id}:{target_position}":
            _fail("EOS_DIAG_PAIRING_INVALID")
        return cls(
            prompt_id,
            _text(item["category"], code),
            target_position,
            pairing_key,
            _boolean(item["eos_target"], code),
            _number(item["eos_logit"], code),
            _number(item["eos_probability"], code, probability=True),
            _integer(item["eos_rank"], code, minimum=1),
            competitor_ids,
            distance,
            _boolean(item["packed_sequence"], code),
            supplied,
        )


@dataclass(frozen=True)
class BoundaryObservation:
    opaque_sample_id: str
    split: str
    packed_sequence: bool
    boundary_index: int
    eos_target_position: int
    boundary_distance: int
    source_sequence_length: int
    target_sequence_length: int
    category: str
    observation_fingerprint: str

    @classmethod
    def from_mapping(cls, value: object) -> BoundaryObservation:
        code = "EOS_DIAG_OBSERVATION_INVALID"
        item = _strict(
            value,
            (
                "opaque_sample_id",
                "split",
                "packed_sequence",
                "boundary_index",
                "eos_target_position",
                "boundary_distance",
                "source_sequence_length",
                "target_sequence_length",
                "category",
                "observation_fingerprint",
            ),
            code,
        )
        semantic = dict(item)
        supplied = _fingerprint(semantic.pop("observation_fingerprint"), code)
        if diagnostic_fingerprint(semantic) != supplied:
            _fail(code)
        return cls(
            _text(item["opaque_sample_id"], code),
            _text(item["split"], code),
            _boolean(item["packed_sequence"], code),
            _integer(item["boundary_index"], code),
            _integer(item["eos_target_position"], code),
            _integer(item["boundary_distance"], code),
            _integer(item["source_sequence_length"], code, minimum=1),
            _integer(item["target_sequence_length"], code, minimum=1),
            _text(item["category"], code),
            supplied,
        )


@dataclass(frozen=True)
class PromptMetadata:
    opaque_prompt_id: str
    category: str
    prompt_length_bucket: str
    context_class: str
    expected_output_position_bucket: str
    prompt_identity_fingerprint: str

    @classmethod
    def from_mapping(cls, value: object) -> PromptMetadata:
        code = "EOS_DIAG_OBSERVATION_INVALID"
        item = _strict(
            value,
            (
                "opaque_prompt_id",
                "category",
                "prompt_length_bucket",
                "context_class",
                "expected_output_position_bucket",
                "prompt_identity_fingerprint",
            ),
            code,
        )
        semantic = dict(item)
        supplied = _fingerprint(semantic.pop("prompt_identity_fingerprint"), code)
        if diagnostic_fingerprint(semantic) != supplied:
            _fail(code)
        return cls(
            _text(item["opaque_prompt_id"], code),
            _text(item["category"], code),
            _text(item["prompt_length_bucket"], code),
            _text(item["context_class"], code),
            _text(item["expected_output_position_bucket"], code),
            supplied,
        )


@dataclass(frozen=True)
class LoopConfig:
    minimum_repeat_count: int
    minimum_loop_length: int
    persistence_steps: int
    ngram_sizes: tuple[int, ...]
    config_fingerprint: str

    @classmethod
    def from_mapping(cls, value: object) -> LoopConfig:
        code = "EOS_DIAG_LOOP_CONFIG_INVALID"
        item = _strict(
            value,
            (
                "minimum_repeat_count",
                "minimum_loop_length",
                "persistence_steps",
                "ngram_sizes",
                "config_fingerprint",
            ),
            code,
        )
        sizes = item["ngram_sizes"]
        if type(sizes) is not list:
            _fail(code)
        normalized = tuple(_integer(size, code, minimum=1) for size in sizes)
        if tuple(sorted(set(normalized))) != normalized:
            _fail(code)
        semantic = dict(item)
        supplied = _fingerprint(semantic.pop("config_fingerprint"), code)
        if diagnostic_fingerprint(semantic) != supplied:
            _fail(code)
        return cls(
            _integer(item["minimum_repeat_count"], code, minimum=2),
            _integer(item["minimum_loop_length"], code, minimum=1),
            _integer(item["persistence_steps"], code, minimum=1),
            normalized,
            supplied,
        )


@dataclass(frozen=True)
class BudgetEvidence:
    candidate_id: str
    training_token_budget: int
    optimizer_steps: int
    final_loss: float
    perplexity: float
    teacher_forced_eos_rank: float
    teacher_forced_eos_probability: float
    pure_greedy_eos_rate: float
    max_length_rate: float
    repetition_rate: float
    model_config_fingerprint: str
    tokenizer_fingerprint: str
    dataset_fingerprint: str
    evaluation_fingerprint: str
    evidence_fingerprint: str

    @classmethod
    def from_mapping(cls, value: object) -> BudgetEvidence:
        code = "EOS_DIAG_BUDGET_PROXY_INVALID"
        fields = (
            "candidate_id",
            "training_token_budget",
            "optimizer_steps",
            "final_loss",
            "perplexity",
            "teacher_forced_eos_rank",
            "teacher_forced_eos_probability",
            "pure_greedy_eos_rate",
            "max_length_rate",
            "repetition_rate",
            "model_config_fingerprint",
            "tokenizer_fingerprint",
            "dataset_fingerprint",
            "evaluation_fingerprint",
            "evidence_fingerprint",
        )
        item = _strict(value, fields, code)
        semantic = dict(item)
        supplied = _fingerprint(semantic.pop("evidence_fingerprint"), code)
        if diagnostic_fingerprint(semantic) != supplied:
            _fail(code)
        return cls(
            _text(item["candidate_id"], code),
            _integer(item["training_token_budget"], code, minimum=1),
            _integer(item["optimizer_steps"], code, minimum=1),
            _number(item["final_loss"], code),
            _number(item["perplexity"], code),
            _number(item["teacher_forced_eos_rank"], code),
            _number(item["teacher_forced_eos_probability"], code, probability=True),
            _number(item["pure_greedy_eos_rate"], code, probability=True),
            _number(item["max_length_rate"], code, probability=True),
            _number(item["repetition_rate"], code, probability=True),
            _fingerprint(item["model_config_fingerprint"], code),
            _fingerprint(item["tokenizer_fingerprint"], code),
            _fingerprint(item["dataset_fingerprint"], code),
            _fingerprint(item["evaluation_fingerprint"], code),
            supplied,
        )


@dataclass(frozen=True)
class AnalysisResult:
    diagnostic_id: str
    artifact_type: str
    evidence_status: str
    records: tuple[Mapping[str, Any], ...]
    summary: Mapping[str, Any]
    limitations: tuple[str, ...]
    result_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "records", tuple(_freeze(_thaw(item)) for item in self.records)
        )
        object.__setattr__(self, "summary", _freeze(_thaw(self.summary)))

    def artifact_payload(self) -> dict[str, Any]:
        return {
            "analysis_status": self.evidence_status,
            "record_schema_version": RESULT_SCHEMA_VERSION,
            "records": [_thaw(item) for item in self.records],
            "summary": {
                **_thaw(self.summary),
                "result_fingerprint": self.result_fingerprint,
            },
            "limitations": list(self.limitations),
        }


def _result(
    diagnostic_id: str,
    artifact_type: str,
    status: str,
    records: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    limitations: Sequence[str] = (),
) -> AnalysisResult:
    if status not in EVIDENCE_STATUSES:
        _fail("EOS_DIAG_ARTIFACT_PAYLOAD_INVALID")
    ordered_records = tuple(_thaw(item) for item in records)
    semantic = {
        "diagnostic_id": diagnostic_id,
        "artifact_type": artifact_type,
        "evidence_status": status,
        "records": list(ordered_records),
        "summary": _thaw(summary),
        "limitations": list(limitations),
    }
    return AnalysisResult(
        diagnostic_id,
        artifact_type,
        status,
        ordered_records,
        _thaw(summary),
        tuple(limitations),
        diagnostic_fingerprint(semantic),
    )


def _trace_key(trace: SyntheticGenerationTrace) -> tuple[str, str, int, int]:
    return (
        trace.opaque_prompt_id,
        trace.generation_profile_id,
        trace.max_new_tokens,
        trace.seed,
    )


def _validate_traces(
    traces: Sequence[SyntheticGenerationTrace],
) -> tuple[SyntheticGenerationTrace, ...]:
    values = tuple(traces)
    if not values or any(
        not isinstance(item, SyntheticGenerationTrace) for item in values
    ):
        _fail("EOS_DIAG_TRACE_INVALID")
    if (
        len({_trace_key(item) for item in values}) != len(values)
        or len({item.diagnostic_run_id for item in values}) != 1
    ):
        _fail("EOS_DIAG_TRACE_INVALID")
    return tuple(sorted(values, key=_trace_key))


def analyze_d1(
    traces: Sequence[SyntheticGenerationTrace], *, top_k: int = 10
) -> tuple[AnalysisResult, AnalysisResult]:
    values = _validate_traces(traces)
    if type(top_k) is not int or top_k < 1:
        _fail("EOS_DIAG_TRACE_INVALID")
    records: list[dict[str, Any]] = []
    profile_values: dict[str, list[GeneratedStep]] = defaultdict(list)
    step_values: dict[str, list[GeneratedStep]] = defaultdict(list)
    entries: list[int] = []
    for trace in values:
        loop_steps = [
            step.step_index
            for step in trace.generated_steps
            if step.repeated_ngram_hashes
        ]
        loop_onset = min(loop_steps) if loop_steps else None
        top_k_steps = [
            step.step_index for step in trace.generated_steps if step.eos_rank <= top_k
        ]
        if top_k_steps:
            entries.append(min(top_k_steps))
        for step in trace.generated_steps:
            competitor_summary = [
                {"token_id": token, "logit": logit}
                for token, logit in zip(
                    step.top_competitor_token_ids,
                    step.top_competitor_logits,
                    strict=True,
                )
            ]
            records.append(
                {
                    "opaque_prompt_id": trace.opaque_prompt_id,
                    "generation_profile_id": trace.generation_profile_id,
                    "max_new_tokens": trace.max_new_tokens,
                    "decoding_role": trace.decoding_role,
                    "step_index": step.step_index,
                    "step_bucket": _bucket_step(step.step_index),
                    "eos_rank": step.eos_rank,
                    "eos_probability": step.eos_probability,
                    "eos_logit": step.eos_logit,
                    "selected_token_id": step.selected_token_id,
                    "competitor_summary": competitor_summary,
                    "loop_phase": "before"
                    if loop_onset is not None and step.step_index < loop_onset
                    else ("at_or_after" if loop_onset is not None else "not_detected"),
                    "termination_proximity": len(trace.generated_steps)
                    - 1
                    - step.step_index,
                    "is_eos_selected": step.is_eos_selected,
                    "trace_fingerprint": trace.trace_fingerprint,
                }
            )
            profile_values[trace.generation_profile_id].append(step)
            step_values[_bucket_step(step.step_index)].append(step)
    by_profile = {
        key: {
            "count": len(items),
            "mean_eos_rank": _mean([float(x.eos_rank) for x in items]),
            "mean_eos_probability": _mean([x.eos_probability for x in items]),
        }
        for key, items in sorted(profile_values.items())
    }
    by_step = {
        key: {
            "count": len(items),
            "mean_eos_rank": _mean([float(x.eos_rank) for x in items]),
            "mean_eos_probability": _mean([x.eos_probability for x in items]),
        }
        for key, items in sorted(step_values.items())
    }
    trajectory = _result(
        "D1",
        "eos_rank_trajectory",
        "complete",
        records,
        {
            "trace_count": len(values),
            "record_count": len(records),
            "top_k": top_k,
            "first_top_k_entry_step_mean": _mean([float(x) for x in entries]),
            "by_profile": by_profile,
            "by_step_bucket": by_step,
        },
    )
    probability = _result(
        "D1",
        "eos_probability_summary",
        "complete",
        (),
        {
            "trace_count": len(values),
            "mean_eos_probability": _mean(
                [
                    step.eos_probability
                    for trace in values
                    for step in trace.generated_steps
                ]
            ),
            "maximum_eos_probability": max(
                step.eos_probability
                for trace in values
                for step in trace.generated_steps
            ),
            "by_profile": by_profile,
            "by_step_bucket": by_step,
            "trajectory_fingerprint": trajectory.result_fingerprint,
        },
    )
    return trajectory, probability


def analyze_d2(
    teacher: Sequence[TeacherForcedObservation],
    traces: Sequence[SyntheticGenerationTrace],
) -> AnalysisResult:
    values = _validate_traces(traces)
    observations = tuple(teacher)
    keys = [item.pairing_key for item in observations]
    if len(set(keys)) != len(keys):
        _fail("EOS_DIAG_PAIRING_INVALID")
    lookup = {
        f"{trace.opaque_prompt_id}:{step.step_index}": (trace, step)
        for trace in values
        for step in trace.generated_steps
    }
    records = []
    unpaired = 0
    for item in sorted(
        observations, key=lambda x: (x.opaque_prompt_id, x.target_position)
    ):
        pair = lookup.get(item.pairing_key)
        if pair is None:
            unpaired += 1
            continue
        trace, step = pair
        if item.category != trace.prompt_category:
            _fail("EOS_DIAG_PAIRING_INVALID")
        records.append(
            {
                "pairing_key": item.pairing_key,
                "opaque_prompt_id": item.opaque_prompt_id,
                "category": item.category,
                "target_position": item.target_position,
                "teacher_eos_rank": item.eos_rank,
                "autoregressive_eos_rank": step.eos_rank,
                "eos_rank_gap": step.eos_rank - item.eos_rank,
                "teacher_eos_probability": item.eos_probability,
                "autoregressive_eos_probability": step.eos_probability,
                "eos_probability_gap": step.eos_probability - item.eos_probability,
                "teacher_observation_fingerprint": item.observation_fingerprint,
                "trace_fingerprint": trace.trace_fingerprint,
            }
        )
    status = "complete" if records and unpaired == 0 else "insufficient_evidence"
    limitations = () if status == "complete" else ("EXACT_PAIRING_INCOMPLETE",)
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_category[record["category"]].append(record)
    summary = {
        "paired_observation_count": len(records),
        "unpaired_count": unpaired + max(0, len(lookup) - len(records)),
        "mean_eos_rank_gap": _mean([float(x["eos_rank_gap"]) for x in records]),
        "mean_eos_probability_gap": _mean([x["eos_probability_gap"] for x in records]),
        "by_category": {
            key: {
                "count": len(items),
                "mean_rank_gap": _mean([float(x["eos_rank_gap"]) for x in items]),
                "mean_probability_gap": _mean(
                    [x["eos_probability_gap"] for x in items]
                ),
            }
            for key, items in sorted(by_category.items())
        },
    }
    return _result(
        "D2", "teacher_autoregressive_gap", status, records, summary, limitations
    )


def _detect_loop(trace: SyntheticGenerationTrace, config: LoopConfig) -> dict[str, Any]:
    token_ids = [step.selected_token_id for step in trace.generated_steps]
    onset: int | None = None
    loop_type: str | None = None
    loop_length: int | None = None
    repeated_hash: str | None = None
    for index in range(config.minimum_repeat_count - 1, len(token_ids)):
        window = token_ids[index - config.minimum_repeat_count + 1 : index + 1]
        if len(set(window)) == 1:
            onset, loop_type, loop_length = (
                index - config.minimum_repeat_count + 1,
                "repeated_token_run",
                1,
            )
            break
    for size in config.ngram_sizes:
        seen: dict[tuple[int, ...], int] = {}
        for end in range(size, len(token_ids) + 1):
            ngram = tuple(token_ids[end - size : end])
            if ngram in seen and end - size - seen[ngram] >= config.persistence_steps:
                candidate = seen[ngram]
                if onset is None or candidate < onset:
                    onset, loop_type, loop_length = (
                        candidate,
                        f"repeated_{size}gram",
                        size,
                    )
                    repeated_hash = diagnostic_fingerprint({"token_ids": list(ngram)})
                break
            seen.setdefault(ngram, end - size)
    max_period = max(config.minimum_loop_length, max(config.ngram_sizes, default=1))
    for period in range(config.minimum_loop_length, max_period + 1):
        required = period * config.minimum_repeat_count
        for start in range(len(token_ids) - required + 1):
            pattern = token_ids[start : start + period]
            if token_ids[
                start : start + required
            ] == pattern * config.minimum_repeat_count and (
                onset is None or start < onset
            ):
                onset, loop_type, loop_length = start, "periodic_pattern", period
                repeated_hash = diagnostic_fingerprint({"token_ids": pattern})
    detected = onset is not None
    before = (
        trace.generated_steps[onset - 1].eos_rank if detected and onset > 0 else None
    )
    at = trace.generated_steps[onset].eos_rank if detected else None
    after_index = onset + config.persistence_steps if detected else 0
    after = (
        trace.generated_steps[after_index].eos_rank
        if detected and after_index < len(trace.generated_steps)
        else None
    )
    if detected and repeated_hash is None:
        repeated_hash = diagnostic_fingerprint(
            {"loop_type": loop_type, "onset": onset, "trace": trace.trace_fingerprint}
        )
    return {
        "opaque_prompt_id": trace.opaque_prompt_id,
        "generation_profile_id": trace.generation_profile_id,
        "max_new_tokens": trace.max_new_tokens,
        "loop_detected": detected,
        "onset_step": onset,
        "loop_type": loop_type,
        "loop_length": loop_length,
        "persistence": config.persistence_steps if detected else 0,
        "repeated_ngram_hash": repeated_hash,
        "eos_rank_before_onset": before,
        "eos_rank_at_onset": at,
        "eos_rank_after_onset": after,
        "max_length_hit": trace.termination_type == "max_length",
        "unique_token_ratio": trace.generated_steps[-1].unique_token_ratio_so_far
        if trace.generated_steps
        else 0.0,
        "trace_fingerprint": trace.trace_fingerprint,
    }


def analyze_d3(
    traces: Sequence[SyntheticGenerationTrace], config: LoopConfig
) -> AnalysisResult:
    values = _validate_traces(traces)
    if not isinstance(config, LoopConfig):
        _fail("EOS_DIAG_LOOP_CONFIG_INVALID")
    records = [_detect_loop(trace, config) for trace in values]
    detected = [record for record in records if record["loop_detected"]]
    return _result(
        "D3",
        "loop_analysis",
        "complete",
        records,
        {
            "trace_count": len(records),
            "loop_detected_count": len(detected),
            "loop_rate": _rate(len(detected), len(records)),
            "mean_onset_step": _mean([float(item["onset_step"]) for item in detected]),
            "loop_config_fingerprint": config.config_fingerprint,
        },
    )


def analyze_d4(
    teacher: Sequence[TeacherForcedObservation],
    boundaries: Sequence[BoundaryObservation],
    traces: Sequence[SyntheticGenerationTrace] = (),
) -> AnalysisResult:
    observations = tuple(teacher)
    boundary_values = tuple(boundaries)
    if (
        not observations
        or not boundary_values
        or any(item.sequence_boundary_distance is None for item in observations)
    ):
        return _result(
            "D4",
            "boundary_analysis",
            "insufficient_evidence",
            (),
            {
                "boundary_observation_count": len(boundary_values),
                "teacher_observation_count": len(observations),
                "missing_metadata_count": sum(
                    item.sequence_boundary_distance is None for item in observations
                ),
            },
            ("BOUNDARY_METADATA_INCOMPLETE",),
        )
    groups: dict[str, list[TeacherForcedObservation]] = defaultdict(list)
    for item in observations:
        assert item.sequence_boundary_distance is not None
        groups[_bucket_distance(item.sequence_boundary_distance)].append(item)
    packed_values = {item.packed_sequence for item in observations}
    status = (
        "complete" if packed_values == {False, True} else "complete_with_limitations"
    )
    limitations = (
        () if status == "complete" else ("PACKED_NON_PACKED_COMPARISON_INCOMPLETE",)
    )
    records = [
        {
            "distance_bucket": key,
            "count": len(items),
            "mean_eos_rank": _mean([float(x.eos_rank) for x in items]),
            "mean_eos_probability": _mean([x.eos_probability for x in items]),
            "packed_count": sum(x.packed_sequence for x in items),
            "non_packed_count": sum(not x.packed_sequence for x in items),
        }
        for key, items in sorted(groups.items())
    ]
    return _result(
        "D4",
        "boundary_analysis",
        status,
        records,
        {
            "boundary_observation_count": len(boundary_values),
            "teacher_observation_count": len(observations),
            "boundary_adjacent_sample_count": sum(
                item.boundary_distance <= 2 for item in boundary_values
            ),
            "missing_metadata_count": 0,
            "packed_comparison_available": packed_values == {False, True},
            "autoregressive_trace_count": len(tuple(traces)),
        },
        limitations,
    )


def analyze_d5(
    metadata: Sequence[PromptMetadata],
    traces: Sequence[SyntheticGenerationTrace],
    teacher: Sequence[TeacherForcedObservation],
) -> AnalysisResult:
    values = _validate_traces(traces)
    metadata_values = tuple(metadata)
    lookup = {item.opaque_prompt_id: item for item in metadata_values}
    if len(lookup) != len(metadata_values) or any(
        trace.opaque_prompt_id not in lookup for trace in values
    ):
        _fail("EOS_DIAG_OBSERVATION_INVALID")
    dimensions: dict[str, dict[str, list[SyntheticGenerationTrace]]] = {
        "prompt_length_bucket": defaultdict(list),
        "category": defaultdict(list),
        "output_position_bucket": defaultdict(list),
    }
    for trace in values:
        meta = lookup[trace.opaque_prompt_id]
        if (
            meta.category != trace.prompt_category
            or meta.prompt_length_bucket != trace.prompt_length_bucket
        ):
            _fail("EOS_DIAG_OBSERVATION_INVALID")
        dimensions["prompt_length_bucket"][meta.prompt_length_bucket].append(trace)
        dimensions["category"][meta.category].append(trace)
        dimensions["output_position_bucket"][
            meta.expected_output_position_bucket
        ].append(trace)
    records = []
    for dimension, groups in dimensions.items():
        for bucket, items in sorted(groups.items()):
            records.append(
                {
                    "dimension": dimension,
                    "bucket": bucket,
                    "count": len(items),
                    "eos_termination_count": sum(
                        x.termination_type == "eos" for x in items
                    ),
                    "max_length_count": sum(
                        x.termination_type == "max_length" for x in items
                    ),
                    "incomplete_count": sum(
                        x.termination_type in {"incomplete", "cancelled", "error"}
                        for x in items
                    ),
                    "repetition_count": sum(
                        any(step.repeated_ngram_hashes for step in x.generated_steps)
                        for x in items
                    ),
                    "mean_eos_probability": _mean(
                        [
                            step.eos_probability
                            for x in items
                            for step in x.generated_steps
                        ]
                    ),
                }
            )
    return _result(
        "D5",
        "prompt_category_position_analysis",
        "complete",
        records,
        {
            "prompt_count": len(metadata_values),
            "trace_count": len(values),
            "teacher_observation_count": len(tuple(teacher)),
            "aggregate_count": len(records),
        },
    )


def _length_row(items: Sequence[SyntheticGenerationTrace]) -> dict[str, Any]:
    total = len(items)
    eos = sum(item.termination_type == "eos" for item in items)
    maximum = sum(item.termination_type == "max_length" for item in items)
    incomplete = sum(
        item.termination_type in {"incomplete", "cancelled", "error"} for item in items
    )
    repetition = sum(
        any(step.repeated_ngram_hashes for step in item.generated_steps)
        for item in items
    )
    return {
        "trace_count": total,
        "prompt_count": len({item.opaque_prompt_id for item in items}),
        "profile_count": len({item.generation_profile_id for item in items}),
        "eos_termination_count": eos,
        "eos_termination_rate": _rate(eos, total),
        "max_length_count": maximum,
        "max_length_rate": _rate(maximum, total),
        "repetition_count": repetition,
        "repetition_rate": _rate(repetition, total),
        "incomplete_count": incomplete,
        "incomplete_rate": _rate(incomplete, total),
        "average_generated_length": _mean(
            [float(len(item.generated_steps)) for item in items]
        ),
        "average_unique_token_ratio": _mean(
            [
                item.generated_steps[-1].unique_token_ratio_so_far
                if item.generated_steps
                else 0.0
                for item in items
            ]
        ),
        "prefix_derived_count": sum(item.prefix_derived for item in items),
    }


def analyze_d6(
    traces: Sequence[SyntheticGenerationTrace],
    *,
    expected_prompt_count: int | None = None,
    expected_profile_count: int | None = None,
) -> AnalysisResult:
    values = _validate_traces(traces)
    groups: dict[int, list[SyntheticGenerationTrace]] = defaultdict(list)
    for trace in values:
        if trace.max_new_tokens not in LENGTHS:
            _fail("EOS_DIAG_LENGTH_MATRIX_INVALID")
        groups[trace.max_new_tokens].append(trace)
    if set(groups) != set(LENGTHS):
        _fail("EOS_DIAG_LENGTH_MATRIX_INVALID")
    if expected_prompt_count is not None and any(
        len({x.opaque_prompt_id for x in items}) != expected_prompt_count
        for items in groups.values()
    ):
        _fail("EOS_DIAG_LENGTH_MATRIX_INVALID")
    if expected_profile_count is not None and any(
        len({x.generation_profile_id for x in items}) != expected_profile_count
        for items in groups.values()
    ):
        _fail("EOS_DIAG_LENGTH_MATRIX_INVALID")
    if (
        expected_prompt_count is not None
        and expected_profile_count is not None
        and any(
            len(items) != expected_prompt_count * expected_profile_count
            for items in groups.values()
        )
    ):
        _fail("EOS_DIAG_LENGTH_MATRIX_INVALID")
    records = []
    for length in LENGTHS:
        items = groups[length]
        by_profile = {
            profile: _length_row(
                [item for item in items if item.generation_profile_id == profile]
            )
            for profile in sorted({item.generation_profile_id for item in items})
        }
        records.append(
            {
                "max_new_tokens": length,
                **_length_row(items),
                "by_profile": by_profile,
                "official_pure_greedy": _length_row(
                    [item for item in items if item.decoding_role == "pure_greedy"]
                ),
                "diagnostic_only": _length_row(
                    [item for item in items if item.decoding_role != "pure_greedy"]
                ),
                "prefix_termination_rule": "eos_within_cutoff_else_max_length_at_cutoff",
            }
        )
    return _result(
        "D6",
        "length_matrix",
        "complete",
        records,
        {
            "lengths": list(LENGTHS),
            "trace_count": len(values),
            "prefix_derived_present": any(item.prefix_derived for item in values),
        },
    )


def analyze_d7(traces: Sequence[SyntheticGenerationTrace]) -> AnalysisResult:
    values = _validate_traces(traces)
    groups: dict[str, list[SyntheticGenerationTrace]] = defaultdict(list)
    for trace in values:
        groups[trace.decoding_role].append(trace)
    if "pure_greedy" not in groups:
        _fail("EOS_DIAG_ABLATION_INVALID")
    baseline = _length_row(groups["pure_greedy"])
    records = []
    for role, items in sorted(groups.items()):
        aggregate = _length_row(items)
        records.append(
            {
                "decoding_role": role,
                "profile_count": len({x.generation_profile_id for x in items}),
                "aggregate": aggregate,
                "delta_from_pure_greedy": {
                    "eos_termination_rate": aggregate["eos_termination_rate"]
                    - baseline["eos_termination_rate"],
                    "max_length_rate": aggregate["max_length_rate"]
                    - baseline["max_length_rate"],
                    "repetition_rate": aggregate["repetition_rate"]
                    - baseline["repetition_rate"],
                    "average_unique_token_ratio": (
                        aggregate["average_unique_token_ratio"] or 0.0
                    )
                    - (baseline["average_unique_token_ratio"] or 0.0),
                },
                "metric_role": "official_pure_model"
                if role == "pure_greedy"
                else "diagnostic_only",
            }
        )
    return _result(
        "D7",
        "decoding_ablation",
        "complete_with_limitations",
        records,
        {
            "pure_greedy_summary": baseline,
            "assisted_termination_heuristic": "disabled_not_supported",
            "hypothesis_role": "H5_diagnostic_only",
            "base_pass_decision_allowed": False,
        },
        ("ASSISTED_TERMINATION_HEURISTIC_UNSUPPORTED",),
    )


def analyze_d8(evidence: Sequence[BudgetEvidence]) -> AnalysisResult:
    values = tuple(sorted(evidence, key=lambda item: item.candidate_id))
    if len(values) != 2 or len({item.candidate_id for item in values}) != 2:
        return _result(
            "D8",
            "budget_proxy_analysis",
            "insufficient_evidence",
            (),
            {"candidate_count": len(values), "causal_budget_conclusion_allowed": False},
            ("TWO_CANDIDATE_EVIDENCE_REQUIRED",),
        )
    identity_fields = (
        "model_config_fingerprint",
        "tokenizer_fingerprint",
        "dataset_fingerprint",
        "evaluation_fingerprint",
    )
    if any(
        getattr(values[0], field) != getattr(values[1], field)
        for field in identity_fields
    ):
        return _result(
            "D8",
            "budget_proxy_analysis",
            "incompatible_input",
            (),
            {"candidate_count": 2, "causal_budget_conclusion_allowed": False},
            ("CANDIDATE_EVALUATION_IDENTITY_MISMATCH",),
        )
    left, right = values
    record = {
        "from_candidate_id": left.candidate_id,
        "to_candidate_id": right.candidate_id,
        "training_token_budget_delta": right.training_token_budget
        - left.training_token_budget,
        "optimizer_steps_delta": right.optimizer_steps - left.optimizer_steps,
        "final_loss_delta": right.final_loss - left.final_loss,
        "perplexity_delta": right.perplexity - left.perplexity,
        "teacher_forced_eos_rank_delta": right.teacher_forced_eos_rank
        - left.teacher_forced_eos_rank,
        "teacher_forced_eos_probability_delta": right.teacher_forced_eos_probability
        - left.teacher_forced_eos_probability,
        "pure_greedy_eos_rate_delta": right.pure_greedy_eos_rate
        - left.pure_greedy_eos_rate,
        "max_length_rate_delta": right.max_length_rate - left.max_length_rate,
        "repetition_rate_delta": right.repetition_rate - left.repetition_rate,
        "evidence_fingerprints": [
            left.evidence_fingerprint,
            right.evidence_fingerprint,
        ],
    }
    return _result(
        "D8",
        "budget_proxy_analysis",
        "complete_with_limitations",
        (record,),
        {
            "candidate_count": 2,
            "h6_evidence_role": "proxy_only",
            "causal_budget_conclusion_allowed": False,
        },
        ("TWO_POINTS_CANNOT_ESTABLISH_CAUSALITY",),
    )


def build_diagnostic_summary(
    diagnostic_run_id: str, results: Sequence[AnalysisResult]
) -> Mapping[str, Any]:
    _text(diagnostic_run_id, "EOS_DIAG_ARTIFACT_PAYLOAD_INVALID")
    values = tuple(results)
    by_id = {item.diagnostic_id for item in values}
    required = {f"D{index}" for index in range(1, 9)}
    if (
        by_id != required
        or len([item for item in values if item.diagnostic_id == "D1"]) != 2
    ):
        _fail("EOS_DIAG_ARTIFACT_PAYLOAD_INVALID")
    statuses: dict[str, str] = {}
    for diagnostic_id in sorted(required):
        matching = [
            item.evidence_status
            for item in values
            if item.diagnostic_id == diagnostic_id
        ]
        statuses[diagnostic_id] = (
            "complete"
            if all(item == "complete" for item in matching)
            else (
                "complete_with_limitations"
                if all(
                    item in {"complete", "complete_with_limitations"}
                    for item in matching
                )
                else matching[0]
            )
        )
    complete = [key for key, value in statuses.items() if value == "complete"]
    limited = [
        key for key, value in statuses.items() if value == "complete_with_limitations"
    ]
    insufficient = [
        key for key, value in statuses.items() if value == "insufficient_evidence"
    ]
    incompatible = [
        key for key, value in statuses.items() if value == "incompatible_input"
    ]
    summary = {
        "diagnostic_run_id": diagnostic_run_id,
        "run_mode": "synthetic_only",
        "completed_diagnostics": complete,
        "limited_diagnostics": limited,
        "insufficient_diagnostics": insufficient,
        "incompatible_diagnostics": incompatible,
        "pure_greedy_summary": next(
            item.summary.get("pure_greedy_summary")
            for item in values
            if item.diagnostic_id == "D7"
        ),
        "repetition_summary": next(
            item.summary for item in values if item.diagnostic_id == "D3"
        ),
        "eos_summary": next(
            item.summary
            for item in values
            if item.artifact_type == "eos_probability_summary"
        ),
        "evidence_coverage": {
            "complete_or_limited": len(complete) + len(limited),
            "required": 8,
        },
        "unresolved_questions": insufficient + incompatible,
        "hypothesis_selection_allowed": not insufficient
        and not incompatible
        and not any(item.evidence_status == "blocked" for item in values),
        "actual_candidate_b_status_changed": False,
    }
    return _freeze({**summary, "summary_fingerprint": diagnostic_fingerprint(summary)})


def build_r1_analysis_payloads(
    results: Sequence[AnalysisResult], diagnostic_summary: Mapping[str, Any]
) -> Mapping[str, Mapping[str, Any]]:
    values = tuple(results)
    payloads = {item.artifact_type: item.artifact_payload() for item in values}
    expected = {
        "eos_rank_trajectory",
        "eos_probability_summary",
        "teacher_autoregressive_gap",
        "loop_analysis",
        "boundary_analysis",
        "prompt_category_position_analysis",
        "length_matrix",
        "decoding_ablation",
        "budget_proxy_analysis",
    }
    if set(payloads) != expected:
        _fail("EOS_DIAG_ARTIFACT_PAYLOAD_INVALID")
    payloads["diagnostic_summary"] = _thaw(diagnostic_summary)
    return _freeze(payloads)
