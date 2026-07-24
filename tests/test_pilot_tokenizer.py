from __future__ import annotations

import json

import pytest

from src.tokenizer import TokenizerError
from src.tokenizer.pilot import validate_pilot_tokenizer
from src.tokenizer.tokenizer import EncodedText, SPECIAL_TOKEN_IDS


class FakeTokenizer:
    def __init__(self, _path, *, vocab_size=16_000):
        self.vocab_size = vocab_size
        self.unk_id = 1

    def encode(self, _text, **_kwargs):
        return EncodedText([2, 8, 3], ["<bos>", "▁안녕", "<eos>"])

    def decode(self, _ids, **_kwargs):
        return "안녕"


def _bundle(tmp_path, **changes):
    model = tmp_path / "tokenizer.model"
    model.write_bytes(b"model")
    manifest = {"model_type": "unigram", "hard_vocab_limit": True, "normalization_rule_name": "identity"}
    manifest.update(changes)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return model


def test_pilot_tokenizer_contract_and_fingerprint(monkeypatch, tmp_path):
    monkeypatch.setattr("src.tokenizer.pilot.DohaTokenizer", FakeTokenizer)
    _, report = validate_pilot_tokenizer(_bundle(tmp_path))
    assert report["vocab_size"] == 16_000
    assert report["special_tokens"] == SPECIAL_TOKEN_IDS
    assert report["tokenizer_fingerprint"].startswith("sha256:")


@pytest.mark.parametrize("field,value", [("model_type", "bpe"), ("hard_vocab_limit", False), ("normalization_rule_name", "nmt_nfkc")])
def test_incompatible_sentencepiece_policy_is_blocked(monkeypatch, tmp_path, field, value):
    monkeypatch.setattr("src.tokenizer.pilot.DohaTokenizer", FakeTokenizer)
    with pytest.raises(TokenizerError, match="TOKENIZER_CONFIG_ERROR"):
        validate_pilot_tokenizer(_bundle(tmp_path, **{field: value}))


def test_vocab_must_not_be_automatically_reduced(monkeypatch, tmp_path):
    monkeypatch.setattr("src.tokenizer.pilot.DohaTokenizer", lambda path: FakeTokenizer(path, vocab_size=15_999))
    with pytest.raises(TokenizerError, match="TOKENIZER_VOCAB_SIZE_MISMATCH"):
        validate_pilot_tokenizer(_bundle(tmp_path))
