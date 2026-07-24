from __future__ import annotations

from src.data.sequence_packing import PackingPolicy, pack_sequences


def test_context_256_default_and_eos_separator():
    result = list(pack_sequences([[8] * 255], PackingPolicy()))
    assert len(result) == 1
    assert len(result[0]["input_ids"]) == 256
    assert result[0]["input_ids"][-1] == 3


def test_invalid_token_range_is_rejected():
    import pytest

    with pytest.raises(ValueError, match="음이 아닌"):
        list(pack_sequences([[8, -1]], PackingPolicy(context_length=4)))
