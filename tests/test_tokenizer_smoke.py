from __future__ import annotations

import hashlib
from argparse import Namespace
from pathlib import Path

import pytest

from src.tokenizer.errors import TokenizerError
from src.tokenizer.tokenizer import DohaTokenizer, EncodedText, SPECIAL_TOKEN_IDS, USER_DEFINED_SYMBOLS
from src.tokenizer.trainer import ARTIFACT_FILES, TrainerConfig, train_smoke_tokenizer, validate_synthetic_corpus
from scripts.tokenizer.train_tokenizer import run as run_train_cli


@pytest.fixture(scope="module")
def trained_bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("tokenizer-smoke")
    corpus = Path("tests/fixtures/tokenizer/corpus.txt").resolve()
    output = root / "bundle"
    train_smoke_tokenizer(
        corpus,
        output,
        synthetic_root=corpus.parent,
        config=TrainerConfig(vocab_size=256),
    )
    return output


def test_trainer_creates_exact_smoke_vocabulary_and_artifacts(trained_bundle: Path):
    tokenizer = DohaTokenizer(trained_bundle / "tokenizer.model")
    assert tokenizer.vocab_size == 256
    assert {path.name for path in trained_bundle.iterdir()} == set(ARTIFACT_FILES)


def test_special_tokens_match_adr_003_and_are_not_split(trained_bundle: Path):
    tokenizer = DohaTokenizer(trained_bundle / "tokenizer.model")
    assert {piece: tokenizer.processor.piece_to_id(piece) for piece in SPECIAL_TOKEN_IDS} == SPECIAL_TOKEN_IDS
    for piece in USER_DEFINED_SYMBOLS:
        encoded = tokenizer.encode(piece)
        assert isinstance(encoded, EncodedText)
        assert encoded.ids.count(SPECIAL_TOKEN_IDS[piece]) == 1


def test_encode_decode_and_length_contract(trained_bundle: Path):
    tokenizer = DohaTokenizer(trained_bundle / "tokenizer.model")
    encoded = tokenizer.encode("안녕하세요 도하 모델입니다.", add_bos=True, add_eos=True)
    assert isinstance(encoded, EncodedText)
    assert encoded.ids[0] == SPECIAL_TOKEN_IDS["<bos>"]
    assert encoded.ids[-1] == SPECIAL_TOKEN_IDS["<eos>"]
    assert len(encoded.ids) == len(encoded.pieces)
    with pytest.raises(TokenizerError, match="TOKENIZER_ENCODE_ERROR"):
        tokenizer.encode("안녕하세요 도하 모델입니다.", max_length=2)
    shortened = tokenizer.encode("안녕하세요 도하 모델입니다.", max_length=2, truncation=True)
    assert isinstance(shortened, EncodedText) and len(shortened.ids) == 2


def test_invalid_corpus_empty_corpus_and_duplicate_special_token_are_rejected(tmp_path: Path):
    allowed = tmp_path / "fixtures"
    allowed.mkdir()
    empty = allowed / "empty.txt"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(TokenizerError, match="TOKENIZER_CORPUS_EMPTY"):
        validate_synthetic_corpus(empty, allowed)
    outside = tmp_path / "outside.txt"
    outside.write_text("합성 문장", encoding="utf-8")
    with pytest.raises(TokenizerError, match="TOKENIZER_CORPUS_NOT_SYNTHETIC"):
        validate_synthetic_corpus(outside, allowed)
    invalid = allowed / "invalid.txt"
    invalid.write_bytes(b"\xff")
    with pytest.raises(TokenizerError, match="TOKENIZER_CORPUS_ERROR"):
        validate_synthetic_corpus(invalid, allowed)
    bad_config = TrainerConfig(user_defined_symbols=("<|system|>",) * 4)
    with pytest.raises(TokenizerError, match="TOKENIZER_CONFIG_ERROR"):
        bad_config.validate()


def test_training_is_deterministic_for_same_fixture_and_config(tmp_path: Path):
    corpus = Path("tests/fixtures/tokenizer/corpus.txt").resolve()
    first = tmp_path / "first"
    second = tmp_path / "second"
    one = train_smoke_tokenizer(corpus, first, synthetic_root=corpus.parent, config=TrainerConfig())
    two = train_smoke_tokenizer(corpus, second, synthetic_root=corpus.parent, config=TrainerConfig())
    assert one["fingerprint"] == two["fingerprint"]
    assert hashlib.sha256((first / "tokenizer.model").read_bytes()).digest() == hashlib.sha256(
        (second / "tokenizer.model").read_bytes()
    ).digest()


def test_existing_output_is_not_overwritten(trained_bundle: Path):
    corpus = Path("tests/fixtures/tokenizer/corpus.txt").resolve()
    with pytest.raises(TokenizerError, match="TOKENIZER_ARTIFACT_EXISTS"):
        train_smoke_tokenizer(corpus, trained_bundle, synthetic_root=corpus.parent, config=TrainerConfig())


def test_cli_rejects_output_outside_tests_output():
    args = Namespace(
        corpus="tests/fixtures/tokenizer/corpus.txt",
        output="docs/tokenizer-output",
        vocab_size=256,
        character_coverage=1.0,
        hard_vocab_limit=True,
    )
    with pytest.raises(TokenizerError, match="TOKENIZER_OUTPUT_PATH_ERROR"):
        run_train_cli(args)
