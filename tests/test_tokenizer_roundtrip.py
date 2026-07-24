from __future__ import annotations

from pathlib import Path

import pytest

from src.tokenizer.errors import TokenizerError
from src.tokenizer.tokenizer import DohaTokenizer, EncodedText, SPECIAL_TOKEN_IDS
from src.tokenizer.trainer import TrainerConfig, train_smoke_tokenizer


@pytest.fixture(scope="module")
def tokenizer(tmp_path_factory: pytest.TempPathFactory) -> DohaTokenizer:
    root = tmp_path_factory.mktemp("tokenizer-roundtrip")
    corpus = Path("tests/fixtures/tokenizer/corpus.txt").resolve()
    output = root / "bundle"
    train_smoke_tokenizer(corpus, output, synthetic_root=corpus.parent, config=TrainerConfig())
    return DohaTokenizer(output / "tokenizer.model")


@pytest.mark.parametrize(
    "text",
    [
        "안녕하세요 도하 모델입니다.",
        "tokenizer smoke test 2026",
        "한국어 english 012345",
        "문장 하나 토큰 둘.",
    ],
)
def test_encode_decode_encode_id_roundtrip(tokenizer: DohaTokenizer, text: str):
    assert tokenizer.roundtrip_ids_equal(text)


def test_batch_encode_preserves_record_order(tokenizer: DohaTokenizer):
    rows = tokenizer.encode(["문장 하나", "문장 둘"])
    assert isinstance(rows, list) and len(rows) == 2
    assert all(isinstance(row, EncodedText) for row in rows)
    assert tokenizer.decode(rows[0].ids) == "문장 하나"
    assert tokenizer.decode(rows[1].ids) == "문장 둘"


def test_decode_special_token_policy_and_empty_ids(tokenizer: DohaTokenizer):
    ids = [SPECIAL_TOKEN_IDS["<bos>"], *tokenizer.encode("문장").ids, SPECIAL_TOKEN_IDS["<eos>"]]
    assert "<bos>" in tokenizer.decode(ids)
    assert tokenizer.decode(ids, skip_special_tokens=True) == "문장"
    assert tokenizer.decode([]) == ""


@pytest.mark.parametrize("ids", [[-1], [9999], [True], [1.5]])
def test_invalid_token_ids_are_rejected(tokenizer: DohaTokenizer, ids: list[object]):
    with pytest.raises(TokenizerError, match="TOKENIZER_INVALID_TOKEN_ID"):
        tokenizer.decode(ids)  # type: ignore[arg-type]
