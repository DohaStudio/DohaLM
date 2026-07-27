import math

from src.evaluation.metrics import generation_statistics, prefix_metrics, quantiles, safe_perplexity


def test_perplexity_and_overflow() -> None:
    assert math.isclose(float(safe_perplexity(math.log(10))["perplexity"]), 10.0)
    overflow = safe_perplexity(1000.0)
    assert overflow["perplexity"] is None
    assert overflow["perplexity_overflow"] is True


def test_sequence_distribution_and_continuation() -> None:
    values = quantiles([0.0, 0.25, 0.5, 0.75, 1.0])
    assert values["median"] == 0.5
    assert values["p95"] == 0.95
    assert values["p99"] == 0.99
    result = prefix_metrics([1, 2, 9, 4], [1, 2, 3, 4])
    assert result["prefix_match_length"] == 2
    assert result["first_4_accuracy"] == 0.75
    assert result["exact_continuation"] is False


def test_generation_statistics_do_not_store_tokens() -> None:
    result = generation_statistics([8, 8, 9, 10], eos_id=3, unk_id=1, special_ids=set(range(8)), byte_ids=set())
    assert "tokens" not in result
    assert result["adjacent_repetition_rate"] == 1 / 3
    assert result["distinct_1"] == 0.75
