from __future__ import annotations

from pathlib import Path

import torch

from src.model import DohaLMTiny, ModelConfig
from src.tokenizer import DohaTokenizer, TrainerConfig, train_smoke_tokenizer
from src.training.pilot_pretraining import _generation


def test_actual_sentencepiece_encode_generate_decode(tmp_path):
    corpus = Path("tests/fixtures/tokenizer/corpus.txt").resolve()
    bundle = tmp_path / "tokenizer"
    train_smoke_tokenizer(corpus, bundle, synthetic_root=corpus.parent, config=TrainerConfig(vocab_size=256))
    tokenizer = DohaTokenizer(bundle / "tokenizer.model")
    model = DohaLMTiny(ModelConfig(vocab_size=256, context_length=16, num_layers=1, hidden_size=16, num_heads=4, head_dim=4, ffn_size=32))
    result = _generation(model, tokenizer, "안녕하세요", device=torch.device("cpu"), max_new_tokens=3)
    assert result["prompt_token_count"] > 0
    assert 0 < result["generated_token_count"] <= 3
    assert "token_ids" not in result
    assert result["decoded_text_stored"] is False
    assert result["decoded_sha256"].startswith("sha256:")
    assert result["token_ids_stored"] is False
    assert result["token_ids_sha256"].startswith("sha256:")


def test_generation_respects_context_limit_by_truncating_prompt(tmp_path):
    corpus = Path("tests/fixtures/tokenizer/corpus.txt").resolve()
    bundle = tmp_path / "tokenizer"
    train_smoke_tokenizer(corpus, bundle, synthetic_root=corpus.parent, config=TrainerConfig(vocab_size=256))
    tokenizer = DohaTokenizer(bundle / "tokenizer.model")
    model = DohaLMTiny(ModelConfig(vocab_size=256, context_length=8, num_layers=1, hidden_size=16, num_heads=4, head_dim=4, ffn_size=32))
    result = _generation(model, tokenizer, "아주 긴 한국어 입력 문장입니다", device=torch.device("cpu"), max_new_tokens=2)
    assert result["prompt_token_count"] <= 6
