from __future__ import annotations

import pytest

from src.training import TrainingError, TrainingMetric, summarize_throughput


def metric(step: int, elapsed: float, tokens: int, records: int) -> TrainingMetric:
    return TrainingMetric(step, 1.0, 1e-3, 1.0, 1.0, tokens, records, elapsed, tokens / elapsed if elapsed else 0.0, 0, 0)


def test_throughput_counts_tokens_records_and_steps() -> None:
    report = summarize_throughput([metric(1, 1.0, 10, 2), metric(2, 1.0, 20, 4)])
    assert report.total_tokens == 20
    assert report.total_records == 4
    assert report.total_optimizer_steps == 2


def test_throughput_excludes_warmup_from_numerator_and_denominator() -> None:
    report = summarize_throughput([metric(1, 10.0, 10, 2), metric(2, 1.0, 20, 4)], exclude_warmup_steps=1)
    assert report.total_tokens == 10
    assert report.tokens_per_second == 10.0


def test_throughput_reports_p50_and_p95() -> None:
    report = summarize_throughput([metric(1, 1.0, 10, 1), metric(2, 3.0, 20, 2), metric(3, 2.0, 30, 3)])
    assert report.p50_step_time == 2.0
    assert report.p95_step_time == pytest.approx(2.9)


def test_throughput_reports_records_and_steps_per_second() -> None:
    report = summarize_throughput([metric(1, 2.0, 8, 4), metric(2, 2.0, 16, 8)])
    assert report.records_per_second == 2.0
    assert report.optimizer_steps_per_second == 0.5


@pytest.mark.parametrize("warmup", [-1, 1])
def test_throughput_rejects_invalid_warmup(warmup: int) -> None:
    with pytest.raises(TrainingError):
        summarize_throughput([metric(1, 1.0, 10, 1)], exclude_warmup_steps=warmup)


def test_throughput_rejects_zero_duration() -> None:
    with pytest.raises(TrainingError, match="측정 시간"):
        summarize_throughput([metric(1, 0.0, 10, 1)])
