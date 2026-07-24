"""Tokenizer smoke pipeline 오류 계약."""

from __future__ import annotations


class TokenizerError(RuntimeError):
    """사용자에게 안전하게 표시할 수 있는 tokenizer 오류."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")
