"""Strict compatibility checks for a 16k pilot SentencePiece model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.data.checksums import file_checksum

from .errors import TokenizerError
from .tokenizer import DohaTokenizer, SPECIAL_TOKEN_IDS


def validate_pilot_tokenizer(path: str | Path) -> tuple[DohaTokenizer, dict[str, Any]]:
    model_path = Path(path)
    tokenizer = DohaTokenizer(model_path)
    if tokenizer.vocab_size != 16_000:
        raise TokenizerError("TOKENIZER_VOCAB_SIZE_MISMATCH", "pilot vocabulary는 정확히 16,000이어야 합니다.")
    manifest_path = model_path.parent / "manifest.json"
    try:
        import json
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TokenizerError("TOKENIZER_MANIFEST_ERROR", "pilot tokenizer manifest를 읽을 수 없습니다.") from exc
    trainer = manifest.get("trainer_config", {})
    if not isinstance(trainer, dict):
        trainer = {}
    model_type = manifest.get("model_type", trainer.get("model_type"))
    hard_vocab_limit = manifest.get("hard_vocab_limit", trainer.get("hard_vocab_limit"))
    normalization = manifest.get("normalization_rule_name", trainer.get("normalization_rule_name"))
    if model_type != "unigram":
        raise TokenizerError("TOKENIZER_CONFIG_ERROR", "pilot tokenizer는 Unigram이어야 합니다.")
    if hard_vocab_limit is not True:
        raise TokenizerError("TOKENIZER_CONFIG_ERROR", "pilot tokenizer는 hard_vocab_limit=true여야 합니다.")
    if normalization != "identity":
        raise TokenizerError("TOKENIZER_CONFIG_ERROR", "pilot tokenizer normalization은 identity여야 합니다.")
    smoke = "안녕하세요 한국어 언어 모델"
    encoded = tokenizer.encode(smoke, add_bos=True, add_eos=True)
    decoded = tokenizer.decode(encoded.ids, skip_special_tokens=True)
    if not decoded.strip() or any(not 0 <= token < tokenizer.vocab_size for token in encoded.ids):
        raise TokenizerError("TOKENIZER_ENCODE_ERROR", "pilot tokenizer encode/decode smoke가 실패했습니다.")
    return tokenizer, {
        "tokenizer_fingerprint": file_checksum(model_path),
        "vocab_size": tokenizer.vocab_size,
        "model_type": "unigram",
        "normalization_rule_name": "identity",
        "hard_vocab_limit": True,
        "special_tokens": dict(SPECIAL_TOKEN_IDS),
        "smoke_unknown_ratio": encoded.ids.count(tokenizer.unk_id) / max(1, len(encoded.ids)),
    }
