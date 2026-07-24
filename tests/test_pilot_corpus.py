from __future__ import annotations

import json

import pytest

from src.data.pilot_corpus import PilotCorpusError, PilotCorpusPolicy, inspect_pilot_corpus, iter_pilot_records, stable_split


def test_txt_stream_summary_and_fingerprint_are_deterministic(tmp_path):
    path = tmp_path / "corpus.txt"
    path.write_text("가나다\n라마바\n", encoding="utf-8")
    policy = PilotCorpusPolicy("fixture", "pending_terms_review", True)
    first = inspect_pilot_corpus(path, policy=policy)
    second = inspect_pilot_corpus(path, policy=policy)
    assert first == second
    assert first.record_count == 2 and first.local_experiment_only
    assert [record.text for record in iter_pilot_records(path)] == ["가나다", "라마바"]


def test_jsonl_requires_explicit_text_and_rejects_field_mixing(tmp_path):
    path = tmp_path / "corpus.jsonl"
    path.write_text(json.dumps({"text_normalized": "안녕", "metadata": {}}) + "\n", encoding="utf-8")
    with pytest.raises(PilotCorpusError, match="PILOT_FIELD_MIXING"):
        list(iter_pilot_records(path))


@pytest.mark.parametrize("text,code", [("\x00", "PILOT_TEXT_NUL"), ("e\u0301", "PILOT_TEXT_NOT_NFC")])
def test_invalid_text_fails_closed_without_echo(tmp_path, text, code):
    path = tmp_path / "corpus.txt"
    path.write_text(text + "\n", encoding="utf-8")
    with pytest.raises(PilotCorpusError, match=code) as caught:
        list(iter_pilot_records(path))
    assert text not in str(caught.value)


def test_pending_license_requires_strict_local_only_flags():
    PilotCorpusPolicy("fixture", "pending_terms_review", True).validate()
    with pytest.raises(PilotCorpusError, match="PILOT_LICENSE_NOT_APPROVED"):
        PilotCorpusPolicy("fixture", "pending_terms_review", False).validate()
    with pytest.raises(PilotCorpusError, match="PILOT_LOCAL_ONLY_VIOLATION"):
        PilotCorpusPolicy("fixture", "pending_terms_review", True, publish_allowed=True).validate()


def test_split_is_stable_and_duplicates_cannot_cross_splits():
    fingerprint = "sha256:" + "a" * 64
    assert stable_split(fingerprint, seed=17) == stable_split(fingerprint, seed=17)
