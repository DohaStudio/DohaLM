"""Operating 16k SentencePiece candidate training and aggregate comparison."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sys
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import sentencepiece as spm
import yaml

from .fingerprint import build_fingerprint, sha256_file
from .tokenizer import DohaTokenizer, SPECIAL_TOKEN_IDS, USER_DEFINED_SYMBOLS


@dataclass(frozen=True)
class OperatingTrainerConfig:
    model_type: str
    vocab_size: int = 16_000
    character_coverage: float = 0.9995
    normalization_rule_name: str = "identity"
    byte_fallback: bool = False
    hard_vocab_limit: bool = True
    shuffle_input_sentence: bool = False
    num_threads: int = 1
    split_digits: bool = True
    split_by_unicode_script: bool = True
    split_by_whitespace: bool = True
    split_by_number: bool = True
    max_sentence_length: int = 16_384
    input_sentence_size: int = 1_000_000
    seed_sentencepiece_size: int = 1_000_000
    remove_extra_whitespaces: bool = True
    add_dummy_prefix: bool = True
    escape_whitespaces: bool = True
    allow_whitespace_only_pieces: bool = False
    treat_whitespace_as_suffix: bool = False
    minloglevel: int = 2

    def validate(self) -> None:
        if self.model_type not in {"unigram", "bpe"}:
            raise ValueError("model_type must be unigram or bpe")
        if self.vocab_size != 16_000 or not 0.98 <= self.character_coverage <= 1.0:
            raise ValueError("operating tokenizer requires vocab_size=16000 and valid coverage")
        if self.normalization_rule_name != "identity" or not self.hard_vocab_limit:
            raise ValueError("operating tokenizer requires identity normalization and hard vocab limit")
        if self.num_threads <= 0:
            raise ValueError("num_threads must be positive")
        if not self.escape_whitespaces:
            raise ValueError("operating tokenizer requires escaped whitespace pieces")
        if self.minloglevel not in {0, 1, 2, 3}:
            raise ValueError("minloglevel must be between 0 and 3")


class _PeakMemoryMonitor:
    """Best-effort process RSS sampler without adding a runtime dependency."""

    def __init__(self, interval_seconds: float = 0.05):
        self.interval_seconds = interval_seconds
        self.peak_bytes = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _current_rss_bytes() -> int:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(ProcessMemoryCounters),
                wintypes.DWORD,
            ]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            handle = kernel32.GetCurrentProcess()
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return 0
            return int(counters.WorkingSetSize)
        try:
            import resource

            maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return int(maximum * (1024 if sys.platform != "darwin" else 1))
        except (ImportError, OSError):
            return 0

    def _sample(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.peak_bytes = max(self.peak_bytes, self._current_rss_bytes())

    def __enter__(self) -> "_PeakMemoryMonitor":
        self.peak_bytes = self._current_rss_bytes()
        self._thread = threading.Thread(target=self._sample, name="tokenizer-rss-monitor", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        self.peak_bytes = max(self.peak_bytes, self._current_rss_bytes())


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path.name}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _sample_lines(corpus: Path, limit: int = 10_000) -> list[str]:
    rows: list[str] = []
    with corpus.open("r", encoding="utf-8") as handle:
        for line in handle:
            value = line.rstrip("\n")
            if value.strip():
                rows.append(value)
                if len(rows) >= limit:
                    break
    if not rows:
        raise ValueError("corpus has no non-empty lines")
    return rows


def build_evaluation_sample_manifest(corpus_manifest: dict[str, Any], rows: list[str]) -> dict[str, Any]:
    digest = hashlib.sha256()
    for row in rows:
        encoded = row.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    payload = {
        "schema_version": "1.0",
        "artifact_kind": "tokenizer_evaluation_sample_manifest",
        "source_split": "Training",
        "selection": "first_non_empty_physical_lines",
        "seed": None,
        "line_count": len(rows),
        "corpus_fingerprint": corpus_manifest["corpus_fingerprint"],
        "corpus_sha256": corpus_manifest["corpus_sha256"],
        "sample_content_sha256": f"sha256:{digest.hexdigest()}",
        "actual_text_values_stored": False,
        "validation_evaluation_benchmark_used": False,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**payload, "sample_fingerprint": f"sha256:{hashlib.sha256(canonical).hexdigest()}"}


def _piece_category(piece: str) -> str:
    visible = piece.replace("▁", "")
    if not visible:
        return "whitespace"
    if any("가" <= char <= "힣" or "ㄱ" <= char <= "ㅣ" for char in visible):
        return "korean"
    if any(char.isascii() and char.isalpha() for char in visible):
        return "english"
    if any(char.isdigit() for char in visible):
        return "numeric"
    if all(unicodedata.category(char).startswith(("P", "S")) for char in visible):
        return "punctuation_or_symbol"
    return "other"


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def _text_features(text: str) -> dict[str, bool]:
    return {
        "contains_consecutive_spaces": bool(re.search(r" {2,}", text)),
        "contains_leading_whitespace": bool(text[:1].isspace()),
        "contains_trailing_whitespace": bool(text[-1:].isspace()),
        "contains_newline": "\n" in text or "\r" in text,
        "contains_tab": "\t" in text,
        "contains_control": any(unicodedata.category(char).startswith("C") for char in text),
        "contains_unicode_sensitive": any(
            ord(char) > 0xFFFF or unicodedata.category(char) in {"Co", "Cs", "Sk", "So"}
            for char in text
        ),
    }


def _roundtrip_failure_reason(text: str, decoded: str, *, has_unknown: bool) -> str:
    if text == decoded:
        return "exact"
    if has_unknown:
        return "unknown_substitution"
    canonical_text = re.sub(r"\s+", " ", text).strip()
    canonical_decoded = re.sub(r"\s+", " ", decoded).strip()
    if canonical_text == canonical_decoded:
        return "whitespace_representation"
    if unicodedata.normalize("NFC", text) == unicodedata.normalize("NFC", decoded):
        return "unicode_normalization_representation"
    return "other_information_loss"


def evaluate_candidate(tokenizer: DohaTokenizer, rows: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    encoded_rows: list[list[int]] = []
    total_chars = total_bytes = total_tokens = unknown = unknown_records = roundtrip_ok = 0
    roundtrip_failed_with_unknown = roundtrip_failed_without_unknown = idempotent_ids = 0
    failure_reasons: dict[str, int] = {}
    failure_features: dict[str, int] = {}
    started = time.perf_counter()
    for text in rows:
        ids = tokenizer.processor.encode(text, out_type=int)
        encoded_rows.append(ids)
        total_chars += len(text)
        total_bytes += len(text.encode("utf-8"))
        total_tokens += len(ids)
        unknown += ids.count(tokenizer.unk_id)
        unknown_records += tokenizer.unk_id in ids
    encode_seconds = max(time.perf_counter() - started, 1e-12)
    started = time.perf_counter()
    for text, ids in zip(rows, encoded_rows, strict=True):
        decoded = tokenizer.processor.decode(ids)
        exact = decoded == text
        roundtrip_ok += exact
        idempotent_ids += tokenizer.processor.encode(decoded, out_type=int) == ids
        reason = _roundtrip_failure_reason(text, decoded, has_unknown=tokenizer.unk_id in ids)
        failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
        if not exact:
            for feature, present in _text_features(text).items():
                if present:
                    failure_features[feature] = failure_features.get(feature, 0) + 1
        if not exact and tokenizer.unk_id in ids:
            roundtrip_failed_with_unknown += 1
        elif not exact:
            roundtrip_failed_without_unknown += 1
    decode_seconds = max(time.perf_counter() - started, 1e-12)

    probes = {
        "korean_regular": "한국어 형태소와 띄어쓰기 품질을 확인합니다.",
        "korean_spacing": "한국어 띄어쓰기 검증 문장입니다.",
        "consecutive_spaces": "연속  공백   검증",
        "leading_trailing_spaces": "  앞뒤 공백 검증  ",
        "newline": "첫째 줄\n둘째 줄",
        "tab": "열1\t열2",
        "mixed_korean_english": "도하LM mixed English 문장",
        "integer": "16000 2026 1234567890",
        "date": "2026-07-26 2026/07/26",
        "decimal": "3.14159 0.001 10.0",
        "english": "DohaLM tokenizer handles English text.",
        "mixed_case": "DohaLM API api GPT gpt",
        "symbols": "[]{}()!@#$%^&*+-_=<>/\\|~`",
        "emoji": "합성 이모지 😀 🚀 🧪",
        "extended_unicode": "확장 문자 Ω Ж あ ア",
        "rare_unicode": "희귀 문자 𠀀 𠮷",
        "synthetic_url": "https://example.invalid/path?q=tokenizer",
        "synthetic_email": "tester@example.invalid",
        "synthetic_code": "def add(a, b):\n    return a + b",
    }
    probe_metrics: dict[str, Any] = {}
    for name, text in probes.items():
        ids = tokenizer.processor.encode(text, out_type=int)
        probe_metrics[name] = {
            "character_count": len(text),
            "token_count": len(ids),
            "unknown_token_count": ids.count(tokenizer.unk_id),
            "roundtrip_exact": tokenizer.processor.decode(ids) == text,
            "encode_decode_encode_idempotent": tokenizer.processor.encode(
                tokenizer.processor.decode(ids), out_type=int
            ) == ids,
            "failure_reason": _roundtrip_failure_reason(
                text,
                tokenizer.processor.decode(ids),
                has_unknown=tokenizer.unk_id in ids,
            ),
            "source_features": _text_features(text),
        }

    categories: dict[str, int] = {}
    multi_character_korean = 0
    single_character_pieces = 0
    byte_piece_ids: set[int] = set()
    lexical_piece_lengths: list[int] = []
    for token_id in range(tokenizer.vocab_size):
        piece = tokenizer.processor.id_to_piece(token_id)
        category = _piece_category(piece)
        categories[category] = categories.get(category, 0) + 1
        visible = piece.replace("▁", "")
        if token_id >= len(SPECIAL_TOKEN_IDS) and visible:
            lexical_piece_lengths.append(len(visible))
        if category == "korean" and len(visible) >= 2:
            multi_character_korean += 1
        if token_id >= len(SPECIAL_TOKEN_IDS) and len(visible) == 1:
            single_character_pieces += 1
        if piece.startswith("<0x") and piece.endswith(">"):
            byte_piece_ids.add(token_id)

    byte_piece_tokens = sum(token_id in byte_piece_ids for ids in encoded_rows for token_id in ids)

    evaluation = {
        "schema_version": "1.0",
        "sample_line_count": len(rows),
        "total_characters": total_chars,
        "total_utf8_bytes": total_bytes,
        "total_tokens": total_tokens,
        "average_tokens_per_line": total_tokens / len(rows),
        "tokens_per_character": total_tokens / total_chars if total_chars else 0,
        "token_count_p50": _percentile([len(ids) for ids in encoded_rows], 0.50),
        "token_count_p95": _percentile([len(ids) for ids in encoded_rows], 0.95),
        "token_count_p99": _percentile([len(ids) for ids in encoded_rows], 0.99),
        "vocabulary_coverage": 1 - unknown / total_tokens if total_tokens else 0,
        "unknown_token_count": unknown,
        "unknown_token_ratio": unknown / total_tokens if total_tokens else 0,
        "unknown_record_count": unknown_records,
        "unknown_record_ratio": unknown_records / len(rows),
        "compression_ratio_characters_per_token": total_chars / total_tokens if total_tokens else 0,
        "compression_ratio_utf8_bytes_per_token": total_bytes / total_tokens if total_tokens else 0,
        "average_token_length_characters": total_chars / total_tokens if total_tokens else 0,
        "encode_lines_per_second": len(rows) / encode_seconds,
        "decode_lines_per_second": len(rows) / decode_seconds,
        "roundtrip_exact_ratio": roundtrip_ok / len(rows),
        "encode_decode_encode_idempotent_ratio": idempotent_ids / len(rows),
        "roundtrip_failed_with_unknown_count": roundtrip_failed_with_unknown,
        "roundtrip_failed_without_unknown_count": roundtrip_failed_without_unknown,
        "roundtrip_reason_counts": dict(sorted(failure_reasons.items())),
        "roundtrip_failure_feature_counts": dict(sorted(failure_features.items())),
        "byte_piece_token_count": byte_piece_tokens,
        "byte_piece_token_ratio": byte_piece_tokens / total_tokens if total_tokens else 0,
        "probe_metrics": probe_metrics,
        "actual_text_values_stored": False,
    }
    vocab = {
        "schema_version": "1.0",
        "piece_count": tokenizer.vocab_size,
        "category_counts": dict(sorted(categories.items())),
        "multi_character_korean_piece_count": multi_character_korean,
        "multi_character_korean_piece_ratio": multi_character_korean / tokenizer.vocab_size,
        "single_character_piece_count": single_character_pieces,
        "single_character_piece_ratio": single_character_pieces / tokenizer.vocab_size,
        "byte_piece_count": len(byte_piece_ids),
        "byte_piece_vocab_ratio": len(byte_piece_ids) / tokenizer.vocab_size,
        "average_lexical_piece_length": sum(lexical_piece_lengths) / len(lexical_piece_lengths),
        "special_token_ids": dict(SPECIAL_TOKEN_IDS),
    }
    return evaluation, vocab


def train_operating_candidate(
    corpus_dir: Path,
    output_dir: Path,
    config: OperatingTrainerConfig,
) -> dict[str, Any]:
    config.validate()
    corpus_dir = corpus_dir.resolve()
    corpus = corpus_dir / "corpus.txt"
    corpus_manifest_path = corpus_dir / "corpus-manifest.json"
    if not corpus.is_file() or not corpus_manifest_path.is_file():
        raise ValueError("corpus bundle is incomplete")
    corpus_manifest = _read_json(corpus_manifest_path)
    if corpus_manifest.get("status") != "approved_tokenizer_development":
        raise ValueError("corpus purpose is not approved")
    if corpus_manifest.get("corpus_sha256") != sha256_file(corpus):
        raise ValueError("corpus checksum mismatch")
    output = output_dir.resolve()
    staging = output.with_name(f".{output.name}.staging-{os.getpid()}")
    if output.exists() or staging.exists():
        raise ValueError("tokenizer candidate output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    started = time.perf_counter()
    resolved = asdict(config)
    resolved_bytes = json.dumps(resolved, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    training_config_fingerprint = f"sha256:{hashlib.sha256(resolved_bytes).hexdigest()}"
    try:
        model_prefix = staging / "tokenizer"
        with _PeakMemoryMonitor() as memory_monitor:
            spm.SentencePieceTrainer.train(
                input=str(corpus),
                model_prefix=str(model_prefix),
                model_type=config.model_type,
                vocab_size=config.vocab_size,
                character_coverage=config.character_coverage,
                normalization_rule_name=config.normalization_rule_name,
                byte_fallback=config.byte_fallback,
                hard_vocab_limit=config.hard_vocab_limit,
                shuffle_input_sentence=config.shuffle_input_sentence,
                num_threads=config.num_threads,
                split_digits=config.split_digits,
                split_by_unicode_script=config.split_by_unicode_script,
                split_by_whitespace=config.split_by_whitespace,
                split_by_number=config.split_by_number,
                max_sentence_length=config.max_sentence_length,
                input_sentence_size=config.input_sentence_size,
                seed_sentencepiece_size=config.seed_sentencepiece_size,
                remove_extra_whitespaces=config.remove_extra_whitespaces,
                add_dummy_prefix=config.add_dummy_prefix,
                escape_whitespaces=config.escape_whitespaces,
                allow_whitespace_only_pieces=config.allow_whitespace_only_pieces,
                treat_whitespace_as_suffix=config.treat_whitespace_as_suffix,
                minloglevel=config.minloglevel,
                pad_id=0,
                unk_id=1,
                bos_id=2,
                eos_id=3,
                pad_piece="<pad>",
                unk_piece="<unk>",
                bos_piece="<bos>",
                eos_piece="<eos>",
                user_defined_symbols=list(USER_DEFINED_SYMBOLS),
            )
        elapsed = time.perf_counter() - started
        tokenizer = DohaTokenizer(staging / "tokenizer.model")
        if tokenizer.vocab_size != 16_000:
            raise ValueError("actual vocabulary size is not 16000")
        if {piece: tokenizer.processor.piece_to_id(piece) for piece in SPECIAL_TOKEN_IDS} != SPECIAL_TOKEN_IDS:
            raise ValueError("special token mapping mismatch")
        rows = _sample_lines(corpus)
        evaluation_sample_manifest = build_evaluation_sample_manifest(corpus_manifest, rows)
        evaluation, vocab_statistics = evaluate_candidate(tokenizer, rows)
        fingerprint = build_fingerprint(staging / "tokenizer.model", resolved, SPECIAL_TOKEN_IDS, spm.__version__)
        manifest = {
            "schema_version": "1.0",
            "artifact_kind": "operating_tokenizer_candidate",
            "status": "candidate_review",
            "purpose": "operating_16k_tokenizer_development_only",
            "model_type": config.model_type,
            "vocab_size": 16_000,
            "actual_piece_count": tokenizer.vocab_size,
            "trainer_config": resolved,
            "training_config_fingerprint": training_config_fingerprint,
            "special_tokens": dict(SPECIAL_TOKEN_IDS),
            "sentencepiece_version": spm.__version__,
            "corpus_fingerprint": corpus_manifest["corpus_fingerprint"],
            "corpus_sha256": corpus_manifest["corpus_sha256"],
            "model_checksum": sha256_file(staging / "tokenizer.model"),
            "vocab_checksum": sha256_file(staging / "tokenizer.vocab"),
            "tokenizer_fingerprint": fingerprint["fingerprint"],
            "training_seconds": elapsed,
            "peak_process_rss_bytes": memory_monitor.peak_bytes or None,
            "peak_process_rss_sampling_interval_seconds": memory_monitor.interval_seconds,
            "evaluation_sample_fingerprint": evaluation_sample_manifest["sample_fingerprint"],
            "environment": {"python": sys.version.split()[0], "platform": platform.platform(), "sentencepiece": spm.__version__},
            "model_training_allowed": False,
            "gate3_effect": "evidence_only_pending_user_approval",
        }
        shutil.copy2(corpus_manifest_path, staging / "corpus-manifest.json")
        (staging / "tokenizer-config.yaml").write_text(yaml.safe_dump(resolved, allow_unicode=True, sort_keys=True), encoding="utf-8", newline="\n")
        _write_json(staging / "tokenizer-manifest.json", manifest)
        _write_json(staging / "fingerprint.json", fingerprint)
        _write_json(staging / "tokenizer-statistics.json", {**evaluation, "vocabulary": vocab_statistics})
        _write_json(staging / "tokenizer-evaluation.json", evaluation)
        _write_json(staging / "vocabulary-statistics.json", vocab_statistics)
        _write_json(staging / "evaluation-sample.manifest.json", evaluation_sample_manifest)
        (staging / "training-log.txt").write_text(
            f"status=candidate_review\nmodel_type={config.model_type}\nvocab_size=16000\n"
            f"training_seconds={elapsed:.6f}\npeak_process_rss_bytes={memory_monitor.peak_bytes or 'unavailable'}\n"
            "model_training_allowed=false\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(staging, output)
        return {**manifest, "evaluation": evaluation, "vocabulary_statistics": vocab_statistics}
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def _candidate_summary(
    root: Path,
    evaluation: dict[str, Any],
    vocabulary: dict[str, Any],
    *,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    manifest = _read_json(root / "tokenizer-manifest.json")
    return {
        "candidate_id": candidate_id or f"{root.parent.parent.name}/{root.name}",
        "model_type": manifest["model_type"],
        "vocab_size": manifest["actual_piece_count"],
        "tokenizer_fingerprint": manifest["tokenizer_fingerprint"],
        "training_config_fingerprint": manifest.get("training_config_fingerprint"),
        "trainer_config": manifest["trainer_config"],
        "training_seconds": manifest["training_seconds"],
        "peak_process_rss_bytes": manifest.get("peak_process_rss_bytes"),
        "model_bytes": (root / "tokenizer.model").stat().st_size,
        "vocab_bytes": (root / "tokenizer.vocab").stat().st_size,
        **{key: evaluation[key] for key in (
            "total_tokens", "average_tokens_per_line", "tokens_per_character",
            "token_count_p50", "token_count_p95", "token_count_p99",
            "vocabulary_coverage", "unknown_token_ratio", "compression_ratio_characters_per_token",
            "compression_ratio_utf8_bytes_per_token", "average_token_length_characters",
            "encode_lines_per_second", "decode_lines_per_second", "roundtrip_exact_ratio",
            "unknown_record_ratio", "encode_decode_encode_idempotent_ratio",
            "roundtrip_failed_with_unknown_count", "roundtrip_failed_without_unknown_count",
            "roundtrip_reason_counts", "roundtrip_failure_feature_counts",
            "byte_piece_token_count", "byte_piece_token_ratio", "probe_metrics",
        )},
        "multi_character_korean_piece_ratio": vocabulary["multi_character_korean_piece_ratio"],
        "single_character_piece_ratio": vocabulary["single_character_piece_ratio"],
        "byte_piece_count": vocabulary["byte_piece_count"],
        "byte_piece_vocab_ratio": vocabulary["byte_piece_vocab_ratio"],
        "vocabulary_category_counts": vocabulary["category_counts"],
    }


def compare_candidates(first_dir: Path, second_dir: Path, output_path: Path) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for root in (first_dir, second_dir):
        evaluation = _read_json(root / "tokenizer-evaluation.json")
        vocabulary = _read_json(root / "vocabulary-statistics.json")
        candidates.append(_candidate_summary(root, evaluation, vocabulary))
    next(item for item in candidates if item["model_type"] == "unigram")
    next(item for item in candidates if item["model_type"] == "bpe")
    recommendation = "unigram"
    reasons = [
        "ADR-003 approved baseline",
        "equal 16k vocabulary and special-token contract",
        "BPE remains a comparison candidate and selecting it would require an ADR change",
    ]
    result = {
        "schema_version": "1.0",
        "artifact_kind": "operating_tokenizer_candidate_comparison",
        "candidates": candidates,
        "recommended_model_type": recommendation,
        "recommendation_reasons": reasons,
        "gate3_status": "planned_pending_user_approval",
        "model_training_allowed": False,
    }
    _write_json(output_path, result)
    return result


def compare_candidate_set(
    corpus_dir: Path,
    candidate_roots: dict[str, Path],
    output_path: Path,
) -> dict[str, Any]:
    """Evaluate multiple immutable bundles on one reproducible Training sample."""

    corpus_root = corpus_dir.resolve()
    corpus_manifest = _read_json(corpus_root / "corpus-manifest.json")
    if corpus_manifest.get("corpus_sha256") != sha256_file(corpus_root / "corpus.txt"):
        raise ValueError("corpus checksum mismatch")
    rows = _sample_lines(corpus_root / "corpus.txt")
    sample_manifest = build_evaluation_sample_manifest(corpus_manifest, rows)
    candidates: list[dict[str, Any]] = []
    for candidate_id, candidate_root in candidate_roots.items():
        root = candidate_root.resolve()
        validate_operating_candidate(root)
        evaluation, vocabulary = evaluate_candidate(DohaTokenizer(root / "tokenizer.model"), rows)
        candidates.append(_candidate_summary(root, evaluation, vocabulary, candidate_id=candidate_id))

    eligible = [
        item for item in candidates
        if item["vocab_size"] == 16_000 and item["unknown_token_ratio"] == 0
    ]
    ranked = sorted(
        eligible or candidates,
        key=lambda item: (
            item["unknown_record_ratio"],
            -item["roundtrip_exact_ratio"],
            -item["encode_decode_encode_idempotent_ratio"],
            item["model_type"] != "unigram",
        ),
    )
    recommendation = ranked[0]["candidate_id"]
    result = {
        "schema_version": "2.0",
        "artifact_kind": "operating_tokenizer_cross_version_comparison",
        "evaluation_sample": sample_manifest,
        "candidates": candidates,
        "recommended_candidate_id": recommendation,
        "recommendation_policy": [
            "exact 16000 vocabulary and special-token contract required",
            "zero unknown token candidates preferred",
            "higher exact round-trip and ID stability preferred",
            "Unigram preferred on remaining ties because ADR-003 is approved",
        ],
        "gate3_status": "planned_pending_user_approval",
        "model_training_allowed": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(output_path, result)
    _write_json(output_path.parent / "evaluation-sample.manifest.json", sample_manifest)
    return result


def refresh_candidate_evaluation(corpus_dir: Path, candidate_dir: Path) -> dict[str, Any]:
    corpus = corpus_dir.resolve() / "corpus.txt"
    candidate = candidate_dir.resolve()
    tokenizer = DohaTokenizer(candidate / "tokenizer.model")
    evaluation, vocabulary = evaluate_candidate(tokenizer, _sample_lines(corpus))
    _write_json(candidate / "tokenizer-evaluation.json", evaluation)
    _write_json(candidate / "vocabulary-statistics.json", vocabulary)
    _write_json(candidate / "tokenizer-statistics.json", {**evaluation, "vocabulary": vocabulary})
    return evaluation


def validate_operating_candidate(candidate_dir: Path) -> dict[str, Any]:
    candidate = candidate_dir.resolve()
    manifest = _read_json(candidate / "tokenizer-manifest.json")
    tokenizer = DohaTokenizer(candidate / "tokenizer.model")
    if tokenizer.vocab_size != 16_000 or manifest.get("actual_piece_count") != 16_000:
        raise ValueError("candidate piece count mismatch")
    if manifest.get("special_tokens") != SPECIAL_TOKEN_IDS:
        raise ValueError("candidate special token contract mismatch")
    trainer_config = manifest.get("trainer_config", {})
    byte_piece_count = sum(
        tokenizer.processor.id_to_piece(token_id).startswith("<0x")
        and tokenizer.processor.id_to_piece(token_id).endswith(">")
        for token_id in range(tokenizer.vocab_size)
    )
    if trainer_config.get("byte_fallback") and byte_piece_count != 256:
        raise ValueError("byte fallback candidate must contain exactly 256 byte pieces")
    if manifest.get("model_checksum") != sha256_file(candidate / "tokenizer.model"):
        raise ValueError("candidate model checksum mismatch")
    if manifest.get("vocab_checksum") != sha256_file(candidate / "tokenizer.vocab"):
        raise ValueError("candidate vocabulary checksum mismatch")
    fingerprint = build_fingerprint(
        candidate / "tokenizer.model",
        trainer_config,
        manifest.get("special_tokens", {}),
        str(manifest.get("sentencepiece_version")),
    )
    fingerprint_document = _read_json(candidate / "fingerprint.json")
    if fingerprint != fingerprint_document or fingerprint.get("fingerprint") != manifest.get("tokenizer_fingerprint"):
        raise ValueError("candidate fingerprint mismatch")
    return {
        "valid": True,
        "model_type": manifest.get("model_type"),
        "piece_count": tokenizer.vocab_size,
        "byte_piece_count": byte_piece_count,
        "tokenizer_fingerprint": fingerprint["fingerprint"],
    }
