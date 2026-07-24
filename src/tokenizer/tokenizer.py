"""SentencePiece model loading, encode와 decode wrapper."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import sentencepiece as spm

from .errors import TokenizerError


SPECIAL_TOKENS = (
    "<pad>",
    "<unk>",
    "<bos>",
    "<eos>",
    "<|system|>",
    "<|user|>",
    "<|assistant|>",
    "<|end|>",
)
SPECIAL_TOKEN_IDS = {piece: token_id for token_id, piece in enumerate(SPECIAL_TOKENS)}
USER_DEFINED_SYMBOLS = SPECIAL_TOKENS[4:]


@dataclass(frozen=True)
class EncodedText:
    ids: list[int]
    pieces: list[str]


class DohaTokenizer:
    def __init__(self, model_path: str | Path):
        path = Path(model_path)
        if not path.is_file():
            raise TokenizerError("TOKENIZER_MODEL_NOT_FOUND", "tokenizer model이 존재하지 않습니다.")
        self.model_path = path
        self.processor = spm.SentencePieceProcessor(model_file=str(path))
        self._validate_special_tokens()

    @property
    def vocab_size(self) -> int:
        return self.processor.get_piece_size()

    @property
    def unk_id(self) -> int:
        return self.processor.unk_id()

    def _validate_special_tokens(self) -> None:
        actual = {piece: self.processor.piece_to_id(piece) for piece in SPECIAL_TOKENS}
        if actual != SPECIAL_TOKEN_IDS:
            raise TokenizerError("TOKENIZER_SPECIAL_TOKEN_MISMATCH", "ADR-003 special token ID가 일치하지 않습니다.")
        if len(set(actual)) != len(actual):
            raise TokenizerError("TOKENIZER_SPECIAL_TOKEN_MISMATCH", "special token ID가 중복됩니다.")
        for piece in USER_DEFINED_SYMBOLS:
            token_id = actual[piece]
            encoded_ids = self.processor.encode(piece, out_type=int)
            encoded_pieces = [self.processor.id_to_piece(value) for value in encoded_ids]
            non_whitespace = [value for value in encoded_pieces if value != "▁"]
            if non_whitespace != [piece] or encoded_ids.count(token_id) != 1:
                raise TokenizerError("TOKENIZER_SPECIAL_TOKEN_MISMATCH", "user-defined symbol이 단일 piece가 아닙니다.")

    def encode(
        self,
        text: str | Sequence[str],
        *,
        add_bos: bool = False,
        add_eos: bool = False,
        truncation: bool = False,
        max_length: int | None = None,
    ) -> EncodedText | list[EncodedText]:
        if isinstance(text, str):
            return self._encode_one(text, add_bos, add_eos, truncation, max_length)
        if isinstance(text, Sequence) and all(isinstance(item, str) for item in text):
            return [self._encode_one(item, add_bos, add_eos, truncation, max_length) for item in text]
        raise TokenizerError("TOKENIZER_ENCODE_ERROR", "입력은 문자열 또는 문자열 목록이어야 합니다.")

    def _encode_one(
        self,
        text: str,
        add_bos: bool,
        add_eos: bool,
        truncation: bool,
        max_length: int | None,
    ) -> EncodedText:
        if max_length is not None and (isinstance(max_length, bool) or not isinstance(max_length, int) or max_length <= 0):
            raise TokenizerError("TOKENIZER_ENCODE_ERROR", "max_length는 양의 정수여야 합니다.")
        ids = list(self.processor.encode(text, out_type=int))
        if add_bos:
            ids.insert(0, SPECIAL_TOKEN_IDS["<bos>"])
        if add_eos:
            ids.append(SPECIAL_TOKEN_IDS["<eos>"])
        if max_length is not None and len(ids) > max_length:
            if not truncation:
                raise TokenizerError("TOKENIZER_ENCODE_ERROR", "token 길이가 max_length를 초과했습니다.")
            ids = ids[:max_length]
        pieces = [self.processor.id_to_piece(token_id) for token_id in ids]
        return EncodedText(ids, pieces)

    def decode(self, ids: Sequence[int], *, skip_special_tokens: bool = False) -> str:
        if not isinstance(ids, Sequence) or isinstance(ids, (str, bytes)):
            raise TokenizerError("TOKENIZER_INVALID_TOKEN_ID", "token ID 목록이 필요합니다.")
        normalized: list[int] = []
        for token_id in ids:
            if isinstance(token_id, bool) or not isinstance(token_id, int) or not 0 <= token_id < self.vocab_size:
                raise TokenizerError("TOKENIZER_INVALID_TOKEN_ID", "token ID가 vocabulary 범위를 벗어났습니다.")
            normalized.append(token_id)
        try:
            if skip_special_tokens:
                filtered = [token_id for token_id in normalized if token_id not in SPECIAL_TOKEN_IDS.values()]
                return self.processor.decode(filtered)
            if not any(token_id in SPECIAL_TOKEN_IDS.values() for token_id in normalized):
                return self.processor.decode(normalized)
            parts: list[str] = []
            ordinary: list[int] = []
            for token_id in normalized:
                if token_id in SPECIAL_TOKEN_IDS.values():
                    if ordinary:
                        parts.append(self.processor.decode(ordinary))
                        ordinary.clear()
                    parts.append(self.processor.id_to_piece(token_id))
                else:
                    ordinary.append(token_id)
            if ordinary:
                parts.append(self.processor.decode(ordinary))
            return "".join(parts)
        except (RuntimeError, ValueError) as exc:
            raise TokenizerError("TOKENIZER_DECODE_ERROR", "token ID를 decode할 수 없습니다.") from exc

    def roundtrip_ids_equal(self, text: str) -> bool:
        first = self.encode(text)
        assert isinstance(first, EncodedText)
        decoded = self.decode(first.ids)
        second = self.encode(decoded)
        assert isinstance(second, EncodedText)
        return first.ids == second.ids
