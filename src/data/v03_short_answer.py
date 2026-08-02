"""Build and validate the immutable DohaLM v0.3 short-answer Dataset package."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
import yaml

from src.data.artifacts import (
    AtomicArtifactDirectory,
    _fsync_directory,
    write_json,
    write_jsonl,
    write_yaml,
)
from src.data.checksums import canonical_json_bytes, checksum_value, file_checksum
from src.data.v03_quality_validation import (
    assess_candidate,
    select_extractive_variant,
    validate_no_raw_text,
)


DATASET_ID = "DOHALM-V0.3-SHORT-ANSWER-DATASET-20260802-0001"
DATASET_VERSION = "v0.3-short-answer"
SOURCE_FIELDS = frozenset({"instruction", "input", "output", "system"})
PACKAGE_FILES = (
    "generation-policy.yaml",
    "lineage.jsonl",
    "manifest.yaml",
    "quality-sidecar.jsonl",
    "review-queue.jsonl",
    "statistics.json",
    "train.jsonl",
    "validation.jsonl",
)


class V03ShortAnswerError(RuntimeError):
    """Fail-closed error carrying a stable code only."""


def _sha(path: Path) -> str:
    return file_checksum(path).removeprefix("sha256:")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    try:
        values = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise V03ShortAnswerError("JSONL_INVALID") from None
    if any(not isinstance(value, dict) for value in values):
        raise V03ShortAnswerError("JSONL_INVALID")
    return values


def load_policy(path: str | Path) -> dict[str, object]:
    try:
        value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise V03ShortAnswerError("POLICY_INVALID") from None
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("dataset_id") != DATASET_ID
    ):
        raise V03ShortAnswerError("POLICY_INVALID")
    if any(
        value.get(key) is not False
        for key in ("tokenization_allowed", "training_allowed")
    ):
        raise V03ShortAnswerError("POLICY_PERMISSION_INVALID")
    return value


def _source_record_hash(
    split: str, line_index: int, record: Mapping[str, object]
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {"line_index": line_index, "record": dict(record), "split": split}
        )
    ).hexdigest()


def _variant_hash(
    parent: str, variant: str, answer: str, policy_fingerprint: str
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "parent_record_hash": parent,
                "variant_type": variant,
                "canonical_generated_answer": " ".join(answer.split()),
                "generation_policy_fingerprint": policy_fingerprint,
            }
        )
    ).hexdigest()


class QwenSemanticEvaluator:
    """Pinned local Qwen hidden-state cosine evaluator; never calls generate()."""

    def __init__(
        self, model_root: str | Path, *, revision: str, seed: int = 42
    ) -> None:
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.torch = torch
        self.root = Path(model_root).resolve()
        if (
            not (self.root / "model.safetensors").is_file()
            or not (self.root / "tokenizer.json").is_file()
        ):
            raise V03ShortAnswerError("SEMANTIC_MODEL_UNAVAILABLE")
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        torch.use_deterministic_algorithms(True, warn_only=False)
        self.tokenizer = AutoTokenizer.from_pretrained(self.root, local_files_only=True)
        self.model = (
            AutoModel.from_pretrained(
                self.root,
                local_files_only=True,
                dtype=torch.bfloat16,
                attn_implementation="sdpa",
            )
            .eval()
            .to("cuda")
        )
        self.identity = {
            "model_id": "Qwen/Qwen2.5-1.5B-Instruct",
            "model_revision": revision,
            "model_sha256": _sha(self.root / "model.safetensors"),
            "tokenizer_sha256": _sha(self.root / "tokenizer.json"),
            "method": "last-hidden-mean-cosine-v1",
        }

    def token_count(self, value: str) -> int:
        return len(self.tokenizer(value, add_special_tokens=False)["input_ids"])

    def similarities(
        self, sources: Sequence[str], candidates: Sequence[str], *, batch_size: int = 4
    ) -> list[float]:
        torch = self.torch
        all_text = [item for pair in zip(sources, candidates) for item in pair]
        vectors = []
        with torch.inference_mode():
            for start in range(0, len(all_text), batch_size):
                encoded = self.tokenizer(
                    all_text[start : start + batch_size],
                    padding=True,
                    truncation=True,
                    max_length=1536,
                    return_tensors="pt",
                ).to("cuda")
                hidden = self.model(**encoded).last_hidden_state.float()
                mask = encoded["attention_mask"].unsqueeze(-1)
                pooled = (hidden * mask).sum(1) / mask.sum(1).clamp_min(1)
                vectors.extend(torch.nn.functional.normalize(pooled, dim=-1).cpu())
        return [
            float(torch.dot(vectors[index], vectors[index + 1]))
            for index in range(0, len(vectors), 2)
        ]


def _select_dry_run(sidecar: list[dict[str, object]], per_category: int) -> set[int]:
    selected: set[int] = set()
    grouped: dict[str, list[int]] = defaultdict(list)
    for item in sidecar:
        if (
            item.get("split") == "train"
            and int(item.get("assistant_tokens", 0)) > 256
            and item.get("completion_score") == 1.0
            and not item.get("is_strong_repeat_candidate")
            and item.get("category_status") == "resolved"
        ):
            grouped[str(item["category"])].append(int(item["line_index"]))
    for category in sorted(grouped):
        selected.update(grouped[category][:per_category])
    return selected


def generate_candidates(
    *,
    source_root: str | Path,
    evaluator: QwenSemanticEvaluator,
    policy: Mapping[str, object],
    dry_run: bool,
) -> dict[str, object]:
    source = Path(source_root).resolve()
    source_policy = policy["source"]
    assert isinstance(source_policy, Mapping)
    for name, expected in source_policy["checksums"].items():  # type: ignore[union-attr]
        if _sha(source / str(name)) != str(expected):
            raise V03ShortAnswerError("SOURCE_CHECKSUM_MISMATCH")
    train = _read_jsonl(source / "train.jsonl")
    validation = _read_jsonl(source / "validation.jsonl")
    old_sidecar = _read_jsonl(source / "quality-sidecar.jsonl")
    expected_rows = source_policy["rows"]
    assert isinstance(expected_rows, Mapping)
    if (
        len(train) != int(expected_rows["train"])
        or len(validation) != int(expected_rows["validation"])
        or len(old_sidecar) != len(train) + len(validation)
    ):
        raise V03ShortAnswerError("SOURCE_ROW_COUNT_MISMATCH")
    if any(set(record) != SOURCE_FIELDS for record in (*train, *validation)):
        raise V03ShortAnswerError("SOURCE_SCHEMA_INVALID")
    train_sidecar = old_sidecar[: len(train)]
    indexes = (
        _select_dry_run(train_sidecar, int(policy["dry_run"]["records_per_category"]))
        if dry_run
        else {
            int(item["line_index"])
            for item in train_sidecar
            if int(item.get("assistant_tokens", 0)) > 256
            and item.get("completion_score") == 1.0
            and not item.get("is_strong_repeat_candidate")
            and item.get("category_status") == "resolved"
        }
    )
    policy_fingerprint = checksum_value(dict(policy))
    prepared: list[dict[str, object]] = []
    review: list[dict[str, object]] = []
    for index in sorted(indexes):
        record = train[index]
        meta = train_sidecar[index]
        parent = _source_record_hash("train", index, record)
        source_answer = str(record["output"])
        source_tokens = evaluator.token_count(source_answer)
        candidate = select_extractive_variant(
            str(record["instruction"]),
            source_answer,
            token_count=evaluator.token_count,
            minimum_tokens=80,
            maximum_tokens=180,
        )
        if candidate is None:
            candidate = select_extractive_variant(
                str(record["instruction"]),
                source_answer,
                token_count=evaluator.token_count,
                minimum_tokens=181,
                maximum_tokens=320,
            )
        if candidate is None:
            review.append(
                {
                    "candidate_record_hash": None,
                    "parent_record_hash": parent,
                    "source_line_index": index,
                    "category": meta.get("category"),
                    "generation_method": "constrained_abstractive",
                    "quality_scores": None,
                    "review_reasons": [
                        "extractive_target_unavailable",
                        "abstractive_generation_requires_review",
                    ],
                }
            )
            continue
        prepared.append(
            {
                "source_line_index": index,
                "source_record_hash": parent,
                "source_answer": source_answer,
                "candidate": candidate,
                "source_tokens": source_tokens,
                "candidate_tokens": evaluator.token_count(candidate),
                "category": meta.get("category"),
                "category_status": meta.get("category_status"),
            }
        )
    scores = (
        evaluator.similarities(
            [str(item["source_answer"]) for item in prepared],
            [str(item["candidate"]) for item in prepared],
            batch_size=int(policy["semantic_evaluator"]["batch_size"]),  # type: ignore[index]
        )
        if prepared
        else []
    )
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    sidecar_new: list[dict[str, object]] = []
    lineage: list[dict[str, object]] = []
    for item, score in zip(prepared, scores):
        assessment = assess_candidate(
            source_answer=str(item["source_answer"]),
            candidate=str(item["candidate"]),
            source_tokens=int(item["source_tokens"]),
            candidate_tokens=int(item["candidate_tokens"]),
            semantic_score=score,
            semantic_threshold=float(policy["quality"]["semantic_threshold"]),  # type: ignore[index]
            generation_method="extractive",
        )
        record_hash = _variant_hash(
            str(item["source_record_hash"]),
            str(assessment["variant_type"]),
            str(item["candidate"]),
            policy_fingerprint,
        )
        side = {
            "schema_version": 1,
            "record_hash": record_hash,
            "parent_record_hash": item["source_record_hash"],
            "split": "train",
            "variant_type": assessment["variant_type"],
            "generation_method": "extractive",
            "source_line_index": item["source_line_index"],
            "source_record_hash": item["source_record_hash"],
            "category": item["category"],
            "category_status": item["category_status"],
            "source_answer_tokens": item["source_tokens"],
            "generated_answer_tokens": item["candidate_tokens"],
            "compression_ratio": assessment["compression_ratio"],
            "completion_score": assessment["completion_score"],
            "repetition_score": assessment["repetition_score"],
            "semantic_preservation_score": assessment["semantic_preservation_score"],
            "entity_preservation_score": assessment["entity_preservation_score"],
            "numeric_preservation_score": assessment["numeric_preservation_score"],
            "eos_policy_expected": "exactly_one_final_assistant_label",
            "quality_flags": [str(assessment["variant_type"]), "complete"],
            "review_required": assessment["review_required"],
            "accepted": assessment["accepted"],
            "rejection_reasons": assessment["rejection_reasons"],
        }
        validate_no_raw_text(side)
        sidecar_new.append(side)
        lineage.append(
            {
                "record_hash": record_hash,
                "parent_record_hash": item["source_record_hash"],
                "source_split": "train",
                "source_line_index": item["source_line_index"],
                "variant_type": assessment["variant_type"],
                "generation_method": "extractive",
                "generation_run_id": DATASET_ID,
            }
        )
        if assessment["accepted"]:
            source_record = train[int(item["source_line_index"])]
            accepted.append(
                {
                    **source_record,
                    "output": item["candidate"],
                    "_record_hash": record_hash,
                }
            )
        else:
            queue = {
                "candidate_record_hash": record_hash,
                "parent_record_hash": item["source_record_hash"],
                "source_line_index": item["source_line_index"],
                "category": item["category"],
                "generation_method": "extractive",
                "quality_scores": {
                    "semantic": assessment["semantic_preservation_score"],
                    "completion": assessment["completion_score"],
                    "repetition": assessment["repetition_score"],
                    "numeric": assessment["numeric_preservation_score"],
                    "entity": assessment["entity_preservation_score"],
                },
                "review_reasons": assessment["rejection_reasons"],
            }
            validate_no_raw_text(queue)
            review.append(queue)
            rejected.append(side)
    return {
        "train": train,
        "validation": validation,
        "old_sidecar": old_sidecar,
        "accepted": accepted,
        "sidecar_new": sidecar_new,
        "lineage": lineage,
        "review": review,
        "rejected": rejected,
        "attempted": len(indexes),
        "prepared": len(prepared),
        "categories": len(
            {
                str(item["category"])
                for item in train_sidecar
                if int(item["line_index"]) in indexes
            }
        ),
        "policy_fingerprint": policy_fingerprint,
    }


def _rates(result: Mapping[str, object]) -> dict[str, float | int]:
    attempted = int(result["attempted"])
    sidecar = result["sidecar_new"]
    assert isinstance(sidecar, list)
    accepted = result["accepted"]
    review = result["review"]
    assert isinstance(accepted, list) and isinstance(review, list)
    semantic_pass = sum(
        float(item["semantic_preservation_score"]) >= 0.85 for item in sidecar
    )
    completion_pass = sum(item["completion_score"] == 1.0 for item in sidecar)
    repeat = sum(item["repetition_score"] == 3 for item in sidecar)
    numeric = sum(item["numeric_preservation_score"] != 1.0 for item in sidecar)
    entity = sum(item["entity_preservation_score"] != 1.0 for item in sidecar)
    denominator = len(sidecar) or 1
    return {
        "attempted": attempted,
        "accepted": len(accepted),
        "review": len(review),
        "rejected": attempted - len(accepted),
        "acceptance_rate": len(accepted) / attempted if attempted else 0.0,
        "semantic_pass_rate": semantic_pass / denominator,
        "completion_pass_rate": completion_pass / denominator,
        "strong_repetition_rate": repeat / denominator,
        "numeric_mismatch_rate": numeric / denominator,
        "entity_mismatch_rate": entity / denominator,
    }


def validate_dry_run(
    result: Mapping[str, object], policy: Mapping[str, object]
) -> dict[str, float | int]:
    rates = _rates(result)
    thresholds = policy["dry_run"]["thresholds"]  # type: ignore[index]
    dry_run = policy["dry_run"]
    assert isinstance(dry_run, Mapping)
    if (
        rates["attempted"] != int(dry_run["expected_records"])
        or int(result["categories"]) != int(dry_run["expected_categories"])
        or rates["semantic_pass_rate"] < float(thresholds["semantic_pass_rate"])
        or rates["completion_pass_rate"] < float(thresholds["completion_pass_rate"])
        or rates["strong_repetition_rate"] > float(thresholds["strong_repetition_rate"])
        or rates["numeric_mismatch_rate"] != 0
        or rates["entity_mismatch_rate"] != 0
    ):
        raise V03ShortAnswerError("DRY_RUN_QUALITY_GATE_FAILED")
    return rates


def _copy(source: Path, destination: Path) -> None:
    with source.open("rb") as reader, destination.open("xb") as writer:
        shutil.copyfileobj(reader, writer, 1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())


def _write_checksums(root: Path) -> dict[str, str]:
    checksums = {name: _sha(root / name) for name in PACKAGE_FILES}
    with (root / "checksums.sha256").open(
        "x", encoding="ascii", newline="\n"
    ) as stream:
        for name in PACKAGE_FILES:
            stream.write(f"{checksums[name]}  {name}\n")
        stream.flush()
        os.fsync(stream.fileno())
    return checksums


def _jsonl_sha(values: Sequence[Mapping[str, object]]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(canonical_json_bytes(dict(value)))
    return digest.hexdigest()


def publish_package(
    *,
    source_root: str | Path,
    output_root: str | Path,
    policy: Mapping[str, object],
    evaluator: QwenSemanticEvaluator,
    git_head: str,
) -> dict[str, object]:
    output = Path(output_root).resolve()
    if (
        output.exists()
        or output.with_name(output.name + ".staging").exists()
        or output.with_name(output.name + ".failed").exists()
    ):
        raise V03ShortAnswerError("OUTPUT_ID_ALREADY_USED")
    result = generate_candidates(
        source_root=source_root, evaluator=evaluator, policy=policy, dry_run=False
    )
    source = Path(source_root).resolve()
    original_train = result["train"]
    validation = result["validation"]
    accepted = result["accepted"]
    assert (
        isinstance(original_train, list)
        and isinstance(validation, list)
        and isinstance(accepted, list)
    )
    new_train = list(original_train)
    for item in accepted:
        record = {key: item[key] for key in SOURCE_FIELDS}
        new_train.append(record)
    original_sidecar = result["old_sidecar"]
    assert isinstance(original_sidecar, list)
    sidecar_new = result["sidecar_new"]
    assert isinstance(sidecar_new, list)
    accepted_hashes = {str(item["_record_hash"]) for item in accepted}
    accepted_sidecar = [
        item for item in sidecar_new if str(item["record_hash"]) in accepted_hashes
    ]
    accepted_lineage = [
        item
        for item in result["lineage"]
        if str(item["record_hash"]) in accepted_hashes
    ]  # type: ignore[index]
    mapped_original = [
        {
            "schema_version": 1,
            "record_hash": item["record_hash"],
            "parent_record_hash": None,
            "split": item["split"],
            "variant_type": "original",
            "generation_method": "source",
            "source_line_index": item["line_index"],
            "source_record_hash": item["record_hash"],
            "category": item["category"],
            "category_status": item["category_status"],
            "source_answer_tokens": item["assistant_tokens"],
            "generated_answer_tokens": item["assistant_tokens"],
            "compression_ratio": 1.0,
            "completion_score": item["completion_score"],
            "repetition_score": item["repetition_score"],
            "semantic_preservation_score": 1.0,
            "entity_preservation_score": 1.0,
            "numeric_preservation_score": 1.0,
            "eos_policy_expected": "exactly_one_final_assistant_label",
            "quality_flags": item["quality_flags"],
            "review_required": item["review_required"],
            "accepted": True,
            "rejection_reasons": [],
        }
        for item in original_sidecar
    ]
    full_sidecar = mapped_original + accepted_sidecar
    rates = _rates(result)
    variants = Counter(
        str(item["variant_type"]) for item in full_sidecar if item["split"] == "train"
    )
    review = result["review"]
    assert isinstance(review, list)
    category_counts: dict[str, Counter[str]] = defaultdict(Counter)
    generation_method_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for item in accepted_sidecar:
        category = str(item["category"])
        method = str(item["generation_method"])
        category_counts[category].update(("candidates", "accepted"))
        generation_method_counts[method].update(("candidates", "accepted"))
    for item in review:
        category = str(item["category"])
        method = str(item["generation_method"])
        category_counts[category].update(("candidates", "review", "rejected"))
        generation_method_counts[method].update(("candidates", "review", "rejected"))
    category_statistics = {}
    for key, counts in sorted(category_counts.items()):
        category_statistics[key] = {
            **dict(counts),
            "acceptance_rate": counts["accepted"] / (counts["candidates"] or 1),
            "generated_answer_tokens": _summary(
                [
                    float(item["generated_answer_tokens"])
                    for item in sidecar_new
                    if str(item["category"]) == key
                ]
            ),
        }
    generation_method_statistics = {
        key: {
            **dict(counts),
            "acceptance_rate": counts["accepted"] / (counts["candidates"] or 1),
        }
        for key, counts in sorted(generation_method_counts.items())
    }
    review_reasons = Counter(
        str(reason) for item in review for reason in item["review_reasons"]
    )
    train_rows = len(new_train)
    composition = {
        "target": dict(policy["target_composition"]),
        "actual": {
            "original": len(original_train) / train_rows,
            "short": variants.get("short", 0) / train_rows,
            "medium": variants.get("medium", 0) / train_rows,
        },
    }
    composition["difference"] = {
        key: composition["actual"][key] - composition["target"][key]
        for key in ("original", "short", "medium")
    }
    original_lengths = [
        float(item["generated_answer_tokens"])
        for item in mapped_original
        if item["split"] == "train"
    ]
    short_lengths = [
        float(item["generated_answer_tokens"])
        for item in accepted_sidecar
        if item["variant_type"] == "short"
    ]
    medium_lengths = [
        float(item["generated_answer_tokens"])
        for item in accepted_sidecar
        if item["variant_type"] == "medium"
    ]
    accepted_quality = accepted_sidecar
    statistics_value = {
        "source_rows": {"train": len(original_train), "validation": len(validation)},
        "generation": rates,
        "variants": dict(sorted(variants.items())),
        "composition": composition,
        "category": category_statistics,
        "generation_method": generation_method_statistics,
        "length_distribution": {
            "original": _summary(original_lengths),
            "short": _summary(short_lengths),
            "medium": _summary(medium_lengths),
            "combined_train": _summary(
                [*original_lengths, *short_lengths, *medium_lengths]
            ),
        },
        "review_queue": {
            "total": len(review),
            "reasons": dict(sorted(review_reasons.items())),
            "restricted_raw_text_artifact": "absent",
        },
        "quality": {
            "completion_rate": sum(
                item["completion_score"] == 1.0 for item in accepted_quality
            )
            / (len(accepted_quality) or 1),
            "strong_repetition_rate": sum(
                item["repetition_score"] == 3 for item in accepted_quality
            )
            / (len(accepted_quality) or 1),
            "numeric_mismatch": sum(
                item["numeric_preservation_score"] != 1.0
                for item in accepted_quality
            ),
            "entity_mismatch": sum(
                item["entity_preservation_score"] != 1.0 for item in accepted_quality
            ),
            "contradiction_detected": review_reasons["contradiction"],
            "new_fact_detected": review_reasons["new_fact_risk"],
            "semantic": _summary(
                [
                    float(item["semantic_preservation_score"])
                    for item in accepted_quality
                ]
            ),
            "compression": _summary(
                [float(item["compression_ratio"]) for item in accepted_quality]
            ),
            "completion_score": _score_counts(accepted_quality, "completion_score"),
            "repetition_score": _score_counts(accepted_quality, "repetition_score"),
        },
        "lineage": {
            "parent_child_pairs": len(accepted_lineage),
            "missing_parents": 0,
            "hash_collisions": 0,
        },
        "cross_split_duplicate_count": 0,
    }
    source_hashes = {
        hashlib.sha256(canonical_json_bytes(item)).hexdigest() for item in validation
    }
    if any(
        hashlib.sha256(canonical_json_bytes(item)).hexdigest() in source_hashes
        for item in new_train
    ):
        raise V03ShortAnswerError("CROSS_SPLIT_DUPLICATE")
    manifest = {
        "schema_version": 1,
        "dataset_id": DATASET_ID,
        "dataset_version": DATASET_VERSION,
        "source": policy["source"],
        "generation": {
            "policy_id": policy["policy_id"],
            **evaluator.identity,
            "prompt_fingerprint": checksum_value(policy["prompt"]),
            "deterministic": True,
            "attempted_records": rates["attempted"],
            "accepted_records": rates["accepted"],
            "review_records": rates["review"],
            "rejected_records": rates["rejected"],
        },
        "content": {
            "original_rows": len(original_train),
            "short_rows": variants.get("short", 0),
            "medium_rows": variants.get("medium", 0),
            "validation_rows": len(validation),
            "rows_added": len(accepted),
            "rows_removed": 0,
            "source_rows_modified": 0,
        },
        "quality": policy["quality"],
        "lineage": {
            "git_head": git_head,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "execution_allowed": False,
        "tokenization_started": False,
        "training_started": False,
    }
    fingerprints = {
        "sidecar": checksum_value({"records": full_sidecar}),
        "lineage": checksum_value({"records": accepted_lineage}),
        "review_queue": checksum_value({"records": result["review"]}),
        "statistics": checksum_value(statistics_value),
        "generation_policy": checksum_value(dict(policy)),
    }
    fingerprints["manifest"] = checksum_value(dict(manifest))
    source_policy = policy["source"]
    assert isinstance(source_policy, Mapping)
    source_checksums = source_policy["checksums"]
    assert isinstance(source_checksums, Mapping)
    package_algorithm = {
        "algorithm": "canonical-json-ordered-components-v1",
        "components": [
            ["train.jsonl", _jsonl_sha(new_train)],
            ["validation.jsonl", str(source_checksums["validation.jsonl"])],
            ["quality-sidecar", fingerprints["sidecar"]],
            ["lineage", fingerprints["lineage"]],
            ["review-queue", fingerprints["review_queue"]],
            ["statistics", fingerprints["statistics"]],
            ["generation-policy", fingerprints["generation_policy"]],
            ["manifest-semantic", fingerprints["manifest"]],
        ],
    }
    fingerprints["package_algorithm"] = package_algorithm
    fingerprints["package"] = checksum_value(package_algorithm)
    manifest["fingerprints"] = fingerprints
    atomic = AtomicArtifactDirectory(output)
    with atomic as staging:
        write_jsonl(staging / "train.jsonl", new_train)
        _copy(source / "validation.jsonl", staging / "validation.jsonl")
        write_jsonl(staging / "quality-sidecar.jsonl", full_sidecar)
        write_jsonl(staging / "lineage.jsonl", accepted_lineage)
        write_jsonl(staging / "review-queue.jsonl", result["review"])  # type: ignore[arg-type]
        write_yaml(staging / "generation-policy.yaml", dict(policy))
        write_yaml(staging / "manifest.yaml", manifest)
        write_json(staging / "statistics.json", statistics_value)
        checksums = _write_checksums(staging)
        _fsync_directory(staging)
        if (staging / "validation.jsonl").read_bytes() != (
            source / "validation.jsonl"
        ).read_bytes():
            raise V03ShortAnswerError("VALIDATION_CHANGED")
        validate_package(staging, policy=policy)
        atomic.publish()
    return {
        "status": "completed",
        "rates": rates,
        "content": manifest["content"],
        "checksums": checksums,
        "fingerprints": manifest["fingerprints"],
    }


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)

    def pick(ratio: float) -> float:
        return ordered[max(0, math.ceil(len(ordered) * ratio) - 1)]

    return {
        "min": ordered[0],
        "mean": sum(ordered) / len(ordered),
        "p50": pick(0.5),
        "p95": pick(0.95),
        "max": ordered[-1],
    }


def _score_counts(
    records: Sequence[Mapping[str, object]], field: str
) -> dict[str, int]:
    return dict(sorted(Counter(str(item[field]) for item in records).items()))


def validate_package(
    root: str | Path, *, policy: Mapping[str, object]
) -> dict[str, object]:
    path = Path(root)
    expected = frozenset((*PACKAGE_FILES, "checksums.sha256"))
    if frozenset(item.name for item in path.iterdir()) != expected:
        raise V03ShortAnswerError("PACKAGE_FILE_SET_INVALID")
    checksums = {}
    for line in (path / "checksums.sha256").read_text(encoding="ascii").splitlines():
        digest, name = line.split("  ", 1)
        checksums[name] = digest
    if set(checksums) != set(PACKAGE_FILES) or any(
        _sha(path / name) != digest for name, digest in checksums.items()
    ):
        raise V03ShortAnswerError("CHECKSUM_INVALID")
    train = _read_jsonl(path / "train.jsonl")
    validation = _read_jsonl(path / "validation.jsonl")
    sidecar = _read_jsonl(path / "quality-sidecar.jsonl")
    lineage = _read_jsonl(path / "lineage.jsonl")
    review = _read_jsonl(path / "review-queue.jsonl")
    if any(set(item) != SOURCE_FIELDS for item in (*train, *validation)):
        raise V03ShortAnswerError("SOURCE_SCHEMA_INVALID")
    if any(
        validate_no_raw_text(item) is not None for item in (*sidecar, *lineage, *review)
    ):
        raise V03ShortAnswerError("RAW_TEXT_FIELD_FORBIDDEN")
    hashes = [str(item["record_hash"]) for item in sidecar]
    parents = {
        str(item["record_hash"])
        for item in sidecar
        if item["variant_type"] == "original"
    }
    if len(hashes) != len(set(hashes)) or any(
        str(item["parent_record_hash"]) not in parents for item in lineage
    ):
        raise V03ShortAnswerError("LINEAGE_INVALID")
    manifest = yaml.safe_load((path / "manifest.yaml").read_text(encoding="utf-8"))
    statistics_value = json.loads(
        (path / "statistics.json").read_text(encoding="utf-8")
    )
    generation_policy = yaml.safe_load(
        (path / "generation-policy.yaml").read_text(encoding="utf-8")
    )
    if manifest["content"]["validation_rows"] != len(validation) or manifest["content"][
        "rows_added"
    ] != len(lineage):
        raise V03ShortAnswerError("PACKAGE_CONSISTENCY_INVALID")
    if statistics_value["cross_split_duplicate_count"] != 0:
        raise V03ShortAnswerError("CROSS_SPLIT_DUPLICATE")
    source = policy["source"]
    assert isinstance(source, Mapping)
    source_rows = source["rows"]
    source_checksums = source["checksums"]
    assert isinstance(source_rows, Mapping) and isinstance(source_checksums, Mapping)
    original_rows = int(source_rows["train"])
    if (
        _jsonl_sha(train[:original_rows]) != source_checksums["train.jsonl"]
        or checksums["validation.jsonl"] != source_checksums["validation.jsonl"]
    ):
        raise V03ShortAnswerError("SOURCE_COPY_NOT_IDENTICAL")
    fingerprints = manifest.get("fingerprints")
    if not isinstance(fingerprints, Mapping):
        raise V03ShortAnswerError("FINGERPRINT_INVALID")
    manifest_semantic = dict(manifest)
    manifest_semantic.pop("fingerprints", None)
    calculated: dict[str, object] = {
        "sidecar": checksum_value({"records": sidecar}),
        "lineage": checksum_value({"records": lineage}),
        "review_queue": checksum_value({"records": review}),
        "statistics": checksum_value(statistics_value),
        "generation_policy": checksum_value(generation_policy),
        "manifest": checksum_value(manifest_semantic),
    }
    package_algorithm = {
        "algorithm": "canonical-json-ordered-components-v1",
        "components": [
            ["train.jsonl", checksums["train.jsonl"]],
            ["validation.jsonl", checksums["validation.jsonl"]],
            ["quality-sidecar", calculated["sidecar"]],
            ["lineage", calculated["lineage"]],
            ["review-queue", calculated["review_queue"]],
            ["statistics", calculated["statistics"]],
            ["generation-policy", calculated["generation_policy"]],
            ["manifest-semantic", calculated["manifest"]],
        ],
    }
    calculated["package_algorithm"] = package_algorithm
    calculated["package"] = checksum_value(package_algorithm)
    if any(fingerprints.get(key) != value for key, value in calculated.items()):
        raise V03ShortAnswerError("FINGERPRINT_MISMATCH")
    return {
        "rows": {"train": len(train), "validation": len(validation)},
        "checksums": checksums,
    }
