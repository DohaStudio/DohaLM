from __future__ import annotations

import json

import pytest
import torch

from scripts.model import generate_smoke, inspect_model, run_model_smoke


def parse_stdout(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    return json.loads(capsys.readouterr().out)


def test_inspect_model_reports_approved_tiny_count(capsys):
    assert inspect_model.main([]) == 0
    report = parse_stdout(capsys)
    assert report["expected_parameter_count"] == 16_889_856
    assert report["parameter_breakdown"]["total_parameters"] == 16_889_856
    assert report["weight_tied"] is True
    assert report["trainer_implemented"] is False


def test_inspect_model_small_uses_bounded_config(capsys):
    assert inspect_model.main(["--small"]) == 0
    report = parse_stdout(capsys)
    assert report["config"]["vocab_size"] == 128
    assert report["parameter_breakdown"]["total_parameters"] == 21_760


def test_cpu_model_smoke_reports_finite_loss_and_gradients(capsys):
    assert run_model_smoke.main(["--device", "cpu", "--dtype", "float32"]) == 0
    report = parse_stdout(capsys)
    assert report["logits_shape"] == [2, 8, 128]
    assert report["loss_finite"] is True
    assert report["gradients_finite"] is True
    assert report["peak_allocated_mib"] is None


def test_cpu_float16_smoke_returns_concise_error(capsys):
    assert run_model_smoke.main(["--device", "cpu", "--dtype", "float16"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "오류:" in captured.err
    assert "Traceback" not in captured.err


def test_generation_smoke_preserves_prefix_and_range(capsys):
    assert generate_smoke.main(["--device", "cpu", "--max-new-tokens", "3"]) == 0
    report = parse_stdout(capsys)
    assert report["generated_shape"] == [1, 6]
    assert report["prefix_preserved"] is True
    assert report["tokens_in_range"] is True
    assert report["tokenizer_used"] is False


def test_generation_smoke_rejects_context_overflow(capsys):
    assert generate_smoke.main(["--max-new-tokens", "14"]) == 2
    captured = capsys.readouterr()
    assert "GENERATION_CONTEXT_EXCEEDED" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_cuda_float16_model_smoke(capsys):
    assert run_model_smoke.main(["--device", "cuda", "--dtype", "float16"]) == 0
    report = parse_stdout(capsys)
    assert report["loss_finite"] is True
    assert report["gradients_finite"] is True
    assert report["peak_allocated_mib"] > 0
    assert report["peak_reserved_mib"] > 0
