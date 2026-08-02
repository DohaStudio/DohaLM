"""Deterministic model-free samplers for DohaLM v0.3."""

from __future__ import annotations

import hashlib
import json
import os
import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from src.data.artifacts import AtomicArtifactDirectory, _fsync_directory, write_json, write_yaml
from src.data.checksums import checksum_value, file_checksum


class V03SamplerError(RuntimeError):
    """Fail-closed sampler contract error."""


def order_fingerprint(indices: Sequence[int]) -> str:
    payload = json.dumps(list(indices), separators=(",", ":")).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def standard_shuffle(size: int, *, seed: int) -> list[int]:
    if size <= 0 or seed < 0:
        raise V03SamplerError("SAMPLER_ARGUMENT_INVALID")
    values = list(range(size))
    random.Random(seed).shuffle(values)
    return values


def variant_balanced(
    variants: Sequence[str], *, seed: int, draws: int | None = None
) -> list[int]:
    """Draw a 50/50 variant mix with replacement when a stratum is smaller."""

    grouped: dict[str, list[int]] = defaultdict(list)
    for index, variant in enumerate(variants):
        grouped[str(variant)].append(index)
    if set(grouped) != {"original", "short"}:
        raise V03SamplerError("VARIANT_MAPPING_INVALID")
    total = len(variants) if draws is None else draws
    if total <= 0:
        raise V03SamplerError("SAMPLER_ARGUMENT_INVALID")
    rng = random.Random(seed)
    targets = {"original": (total + 1) // 2, "short": total // 2}
    selected: list[int] = []
    for variant in ("original", "short"):
        pool = grouped[variant]
        count = targets[variant]
        if count <= len(pool):
            selected.extend(rng.sample(pool, count))
        else:
            selected.extend(pool)
            selected.extend(rng.choice(pool) for _ in range(count - len(pool)))
    rng.shuffle(selected)
    return selected


def build_parent_groups(rows: Sequence[Mapping[str, object]]) -> list[tuple[int, ...]]:
    original_by_hash: dict[str, int] = {}
    children: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        variant = row.get("variant_type")
        record_hash = row.get("record_hash")
        if not isinstance(record_hash, str) or not record_hash:
            raise V03SamplerError("ROW_IDENTITY_INVALID")
        if variant == "original":
            if record_hash in original_by_hash:
                raise V03SamplerError("PARENT_DUPLICATE")
            original_by_hash[record_hash] = index
        elif variant == "short":
            parent = row.get("parent_record_hash")
            if not isinstance(parent, str) or not parent:
                raise V03SamplerError("PARENT_MISSING")
            children[parent].append(index)
        else:
            raise V03SamplerError("VARIANT_MAPPING_INVALID")
    if any(parent not in original_by_hash for parent in children):
        raise V03SamplerError("PARENT_MISSING")
    if any(len(values) > 1 for values in children.values()):
        raise V03SamplerError("PARENT_CHILD_DUPLICATE")
    return [
        (index, *children.get(record_hash, ()))
        for record_hash, index in original_by_hash.items()
    ]


def parent_group_shuffle(
    rows: Sequence[Mapping[str, object]], *, base_seed: int, epoch: int
) -> list[int]:
    if base_seed < 0 or epoch < 0:
        raise V03SamplerError("SAMPLER_ARGUMENT_INVALID")
    groups = build_parent_groups(rows)
    random.Random(base_seed + epoch).shuffle(groups)
    reverse = epoch % 2 == 1
    first_pass: list[int] = []
    second_pass: list[int] = []
    for group in groups:
        if len(group) == 1:
            first_pass.append(group[0])
        elif reverse:
            first_pass.append(group[1])
            second_pass.append(group[0])
        else:
            first_pass.append(group[0])
            second_pass.append(group[1])
    output = [*first_pass, *second_pass]
    if len(output) != len(rows) or len(set(output)) != len(rows):
        raise V03SamplerError("SAMPLER_COVERAGE_INVALID")
    return output


def summarize_order(
    indices: Sequence[int], rows: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    counts = Counter(indices)
    unique = len(counts)
    positions = {value: index for index, value in enumerate(indices)}
    parent_distances: list[int] = []
    adjacency = 0
    original_index = {
        str(row["record_hash"]): index
        for index, row in enumerate(rows)
        if row["variant_type"] == "original"
    }
    for index, row in enumerate(rows):
        if row["variant_type"] != "short":
            continue
        parent = original_index[str(row["parent_record_hash"])]
        distance = abs(positions[index] - positions[parent])
        parent_distances.append(distance)
        adjacency += distance == 1
    variant_counts = Counter(str(rows[index]["variant_type"]) for index in indices)
    return {
        "draws": len(indices),
        "unique_rows": unique,
        "unique_coverage_ratio": unique / len(rows),
        "duplicate_draws": len(indices) - unique,
        "unsampled_rows": len(rows) - unique,
        "variant_counts": dict(sorted(variant_counts.items())),
        "parent_pair_mean_distance": (
            sum(parent_distances) / len(parent_distances) if parent_distances else 0.0
        ),
        "parent_pair_adjacency_rate": (
            adjacency / len(parent_distances) if parent_distances else 0.0
        ),
        "draw_order_fingerprint": order_fingerprint(indices),
    }


def simulate_policies(
    rows: Sequence[Mapping[str, object]], *, epochs: int = 10, base_seed: int = 42
) -> dict[str, object]:
    if epochs != 10 or len(rows) != 17639:
        raise V03SamplerError("SIMULATION_CONTRACT_INVALID")
    variants = [str(item["variant_type"]) for item in rows]
    policies: dict[str, list[dict[str, object]]] = defaultdict(list)
    for epoch in range(epochs):
        orders = {
            "standard_shuffle": standard_shuffle(len(rows), seed=base_seed + epoch),
            "variant_balanced": variant_balanced(variants, seed=base_seed + epoch),
            "parent_group_shuffle": parent_group_shuffle(rows, base_seed=base_seed, epoch=epoch),
        }
        for name, order in orders.items():
            summary = summarize_order(order, rows)
            summary.update({
                "epoch": epoch,
                "seed": base_seed + epoch,
                "epoch_tokens": sum(int(rows[index]["total_tokens"]) for index in order),
                "assistant_tokens": sum(int(rows[index]["assistant_tokens"]) for index in order),
                "category_counts": dict(sorted(Counter(str(rows[index].get("category")) for index in order).items())),
            })
            policies[name].append(summary)
    deterministic = all(
        parent_group_shuffle(rows, base_seed=base_seed, epoch=epoch)
        == parent_group_shuffle(rows, base_seed=base_seed, epoch=epoch)
        for epoch in range(epochs)
    )
    aggregates = {}
    for name, values in policies.items():
        aggregates[name] = {
            "mean_coverage_ratio": sum(float(item["unique_coverage_ratio"]) for item in values) / epochs,
            "total_duplicate_draws": sum(int(item["duplicate_draws"]) for item in values),
            "total_unsampled_rows": sum(int(item["unsampled_rows"]) for item in values),
            "mean_parent_adjacency_rate": sum(float(item["parent_pair_adjacency_rate"]) for item in values) / epochs,
            "mean_parent_distance": sum(float(item["parent_pair_mean_distance"]) for item in values) / epochs,
            "epoch_tokens": int(values[0]["epoch_tokens"]),
            "assistant_tokens": int(values[0]["assistant_tokens"]),
        }
    selected = aggregates["parent_group_shuffle"]
    if selected["mean_coverage_ratio"] != 1.0 or selected["total_duplicate_draws"] != 0 or selected["total_unsampled_rows"] != 0 or not deterministic:
        raise V03SamplerError("SAMPLER_READINESS_FAILED")
    return {"schema_version": 1, "simulation_id": "DOHALM-V0.3-SAMPLING-SIMULATION-20260802-0001", "epochs": epochs, "base_seed": base_seed, "policies": dict(policies), "aggregates": aggregates, "selected_policy": "parent_group_shuffle", "deterministic": deterministic, "training_started": False}


def publish_simulation(*, tokenized_root: Path, output_root: Path, git_head: str) -> dict[str, object]:
    try:
        rows_value = json.loads((tokenized_root / "row-alignment.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise V03SamplerError("TOKENIZED_ALIGNMENT_INVALID") from None
    if not isinstance(rows_value, dict) or not isinstance(rows_value.get("train"), list):
        raise V03SamplerError("TOKENIZED_ALIGNMENT_INVALID")
    result = simulate_policies(rows_value["train"])
    readiness = {"schema_version": 1, "status": "ready_not_approved", "selected": {"policy": "parent_group_shuffle", "replacement": False, "draws_per_epoch": 17639, "base_seed": 42, "internal_order": "alternating_by_epoch"}, "hard_conditions": {"unique_coverage_ratio": 1.0, "duplicate_draws": 0, "unsampled_rows": 0, "deterministic": True}, "training_allowed": False, "execution_allowed": False}
    manifest = {"schema_version": 1, "simulation_id": result["simulation_id"], "git_head": git_head, "tokenization_id": "DOHALM-V0.3-TOKENIZATION-20260802-0001", "result_fingerprint": checksum_value(result), "readiness_fingerprint": checksum_value(readiness), "training_started": False}
    atomic = AtomicArtifactDirectory(output_root)
    with atomic as staging:
        write_json(staging / "simulation-results.json", result)
        write_yaml(staging / "sampler-readiness.yaml", readiness)
        write_yaml(staging / "simulation-manifest.yaml", manifest)
        checksums = {name: file_checksum(staging / name).removeprefix("sha256:") for name in ("sampler-readiness.yaml", "simulation-manifest.yaml", "simulation-results.json")}
        with (staging / "checksums.sha256").open("x", encoding="ascii", newline="\n") as stream:
            for name, digest in sorted(checksums.items()):
                stream.write(f"{digest}  {name}\n")
            stream.flush()
            os.fsync(stream.fileno())
        for path in staging.iterdir():
            if path.is_file():
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
        _fsync_directory(staging)
        reloaded = json.loads((staging / "simulation-results.json").read_text(encoding="utf-8"))
        if checksum_value(reloaded) != manifest["result_fingerprint"]:
            raise V03SamplerError("SIMULATION_RELOAD_FAILED")
        atomic.publish()
    return {"status": "completed", "simulation_id": result["simulation_id"], "selected_policy": "parent_group_shuffle", "artifact_fingerprint": checksum_value({"algorithm": "ordered-file-checksums-v1", "files": sorted(checksums.items())}), "checksums": checksums, "aggregates": result["aggregates"]}
