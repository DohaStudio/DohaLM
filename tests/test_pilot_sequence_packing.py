from __future__ import annotations

from src.data.sequence_packing import PackingPolicy, pack_sequences


def test_continuous_eos_drop_is_deterministic():
    policy = PackingPolicy(context_length=4)
    records = [[8, 9], [10, 11, 12]]
    first = list(pack_sequences(records, policy))
    second = list(pack_sequences(records, policy))
    assert first == second
    assert first == [{"input_ids": [8, 9, 3, 10], "labels": [8, 9, 3, 10], "attention_mask": [1, 1, 1, 1]}]


def test_padding_masks_labels_with_ignore_index():
    result = list(pack_sequences([[8]], PackingPolicy(context_length=4, remainder="pad")))
    assert result[0]["input_ids"] == [8, 3, 0, 0]
    assert result[0]["labels"] == [8, 3, -100, -100]
    assert result[0]["attention_mask"] == [1, 1, 0, 0]


def test_record_boundary_never_combines_records():
    policy = PackingPolicy(context_length=4, mode="record_boundary", remainder="pad")
    result = list(pack_sequences([[8], [9]], policy))
    assert [row["input_ids"] for row in result] == [[8, 3, 0, 0], [9, 3, 0, 0]]
