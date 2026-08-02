from __future__ import annotations

from src.training.sft_tokenization import EncodedRecord
from src.training.v03_tokenization import analyze_candidates, validate_encoded


def _encoded(length: int, assistant: int = 3) -> EncodedRecord:
    prompt = length - assistant
    return EncodedRecord(
        input_ids=tuple([1] * (length - 1) + [151645]),
        attention_mask=tuple([1] * length),
        labels=tuple([-100] * prompt + [2] * (assistant - 1) + [151645]),
        prompt_tokens=prompt,
        assistant_tokens=assistant,
        user_tokens=max(prompt - 2, 0),
    )


def test_eos_and_assistant_only_mask_contract() -> None:
    validate_encoded(_encoded(20))


def test_smallest_lossless_max_sequence_is_selected() -> None:
    candidates, selected = analyze_candidates([_encoded(900), _encoded(1100)])
    assert candidates["1024"]["total_truncation"] == 1
    assert candidates["1152"]["total_truncation"] == 0
    assert selected == 1152
