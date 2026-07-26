from __future__ import annotations

import io
from pathlib import Path

import pytest
import sentencepiece as spm

from scripts.datasets.json_record_stream import RECORD_OK, scan_json_array_records
from src.data.aihub_71748_tokenizer_corpus import CorpusBuildConfig, _DataInfoArrayStream
from src.tokenizer.operating import (
    OperatingTrainerConfig,
    _PeakMemoryMonitor,
    _roundtrip_failure_reason,
    build_evaluation_sample_manifest,
    evaluate_candidate,
)
from src.tokenizer.tokenizer import DohaTokenizer, SPECIAL_TOKEN_IDS


def test_peak_memory_monitor_reports_process_rss() -> None:
    with _PeakMemoryMonitor(interval_seconds=0.001) as monitor:
        allocation = bytearray(1_000_000)

    assert allocation
    assert monitor.peak_bytes > 0


def test_data_info_array_stream_exposes_records_without_metadata_values() -> None:
    source = io.BytesIO(
        b'{"metadata":{"note":"data_info"},"data_info":'
        b'[{"contents":"first","data_id":"excluded"},{"contents":"second"}]}'
    )
    events = []
    result = scan_json_array_records(
        _DataInfoArrayStream(source),
        max_record_bytes=1024,
        max_read_bytes=4096,
        on_record=events.append,
    )
    assert result.status == RECORD_OK
    assert [event.value["contents"] for event in events] == ["first", "second"]


def test_data_info_array_stream_fails_closed_for_non_array() -> None:
    with pytest.raises(ValueError, match="not an array"):
        _DataInfoArrayStream(io.BytesIO(b'{"data_info":{"contents":"blocked"}}')).read(1)


def test_operating_configs_are_limited_to_two_16k_candidate_types() -> None:
    unigram = OperatingTrainerConfig("unigram")
    unigram.validate()
    assert unigram.input_sentence_size == 1_000_000
    OperatingTrainerConfig("bpe").validate()
    with pytest.raises(ValueError, match="model_type"):
        OperatingTrainerConfig("word").validate()
    with pytest.raises(ValueError, match="vocab_size"):
        OperatingTrainerConfig("unigram", vocab_size=8_000).validate()


def test_corpus_limits_fail_closed() -> None:
    with pytest.raises(ValueError, match="positive"):
        CorpusBuildConfig(records_per_archive=0).validate()


def test_v2_operating_config_preserves_contract() -> None:
    config = OperatingTrainerConfig(
        "unigram",
        character_coverage=1.0,
        byte_fallback=True,
        remove_extra_whitespaces=False,
        add_dummy_prefix=False,
        allow_whitespace_only_pieces=True,
    )
    config.validate()
    assert config.vocab_size == 16_000
    assert config.hard_vocab_limit is True
    assert config.normalization_rule_name == "identity"


def test_evaluation_sample_manifest_is_deterministic_and_value_free() -> None:
    corpus = {"corpus_fingerprint": "sha256:corpus", "corpus_sha256": "sha256:file"}
    rows = ["synthetic one", "합성 둘"]
    first = build_evaluation_sample_manifest(corpus, rows)
    second = build_evaluation_sample_manifest(corpus, list(rows))
    assert first == second
    assert first["line_count"] == 2
    assert first["actual_text_values_stored"] is False
    assert all(row not in str(first) for row in rows)


def test_roundtrip_failure_reason_separates_unknown_and_whitespace() -> None:
    assert _roundtrip_failure_reason("a", "a", has_unknown=False) == "exact"
    assert _roundtrip_failure_reason("a", "b", has_unknown=True) == "unknown_substitution"
    assert _roundtrip_failure_reason("a  b", "a b", has_unknown=False) == "whitespace_representation"
    assert _roundtrip_failure_reason("a", "b", has_unknown=False) == "other_information_loss"


def test_byte_fallback_candidate_keeps_special_ids_and_reports_byte_usage(tmp_path: Path) -> None:
    model = tmp_path / "tokenizer.model"
    corpus = [
        "한국어  consecutive spaces",
        " leading and trailing ",
        "rare unicode 𠀀 𠮷 emoji 😀",
    ] * 100
    model_bytes = io.BytesIO()
    spm.SentencePieceTrainer.train(
        sentence_iterator=iter(corpus),
        model_writer=model_bytes,
        model_type="unigram",
        vocab_size=320,
        hard_vocab_limit=False,
        character_coverage=1.0,
        byte_fallback=True,
        normalization_rule_name="identity",
        remove_extra_whitespaces=False,
        add_dummy_prefix=False,
        allow_whitespace_only_pieces=True,
        minloglevel=2,
        pad_id=0,
        unk_id=1,
        bos_id=2,
        eos_id=3,
        pad_piece="<pad>",
        unk_piece="<unk>",
        bos_piece="<bos>",
        eos_piece="<eos>",
        user_defined_symbols=["<|system|>", "<|user|>", "<|assistant|>", "<|end|>"],
    )
    model.write_bytes(model_bytes.getvalue())
    tokenizer = DohaTokenizer(model)
    assert {piece: tokenizer.processor.piece_to_id(piece) for piece in SPECIAL_TOKEN_IDS} == SPECIAL_TOKEN_IDS
    assert sum(tokenizer.processor.id_to_piece(i).startswith("<0x") for i in range(tokenizer.vocab_size)) == 256
    evaluation, vocabulary = evaluate_candidate(tokenizer, ["unseen rare 𡃁"])
    assert evaluation["unknown_token_count"] == 0
    assert evaluation["byte_piece_token_count"] > 0
    assert vocabulary["byte_piece_count"] == 256
