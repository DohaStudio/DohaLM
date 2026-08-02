from __future__ import annotations

from src.training.v03_sampler import (
    build_parent_groups,
    parent_group_shuffle,
    standard_shuffle,
    summarize_order,
    variant_balanced,
)


def _rows() -> list[dict[str, object]]:
    return [
        {"record_hash": "a", "parent_record_hash": None, "variant_type": "original"},
        {"record_hash": "b", "parent_record_hash": None, "variant_type": "original"},
        {"record_hash": "c", "parent_record_hash": None, "variant_type": "original"},
        {"record_hash": "sa", "parent_record_hash": "a", "variant_type": "short"},
        {"record_hash": "sb", "parent_record_hash": "b", "variant_type": "short"},
    ]


def test_parent_groups_and_shuffle_cover_every_row_once() -> None:
    rows = _rows()
    assert build_parent_groups(rows) == [(0, 3), (1, 4), (2,)]
    order = parent_group_shuffle(rows, base_seed=42, epoch=0)
    assert sorted(order) == list(range(len(rows)))
    assert order == parent_group_shuffle(rows, base_seed=42, epoch=0)
    assert order != parent_group_shuffle(rows, base_seed=42, epoch=1)
    assert summarize_order(order, rows)["parent_pair_adjacency_rate"] == 0.0


def test_parent_internal_order_alternates_by_epoch() -> None:
    rows = _rows()
    even = parent_group_shuffle(rows, base_seed=42, epoch=0)
    odd = parent_group_shuffle(rows, base_seed=42, epoch=1)
    assert even.index(0) < even.index(3)
    assert odd.index(3) < odd.index(0)


def test_standard_and_balanced_contracts() -> None:
    rows = _rows()
    standard = standard_shuffle(len(rows), seed=42)
    assert sorted(standard) == list(range(len(rows)))
    balanced = variant_balanced([str(item["variant_type"]) for item in rows], seed=42)
    assert len(balanced) == len(rows)
    summary = summarize_order(standard, rows)
    assert summary["unique_coverage_ratio"] == 1.0
    assert summary["duplicate_draws"] == 0
