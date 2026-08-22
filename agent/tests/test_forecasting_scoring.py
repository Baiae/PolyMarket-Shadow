from datetime import UTC, datetime

import pytest

from evaluation.scoring import brier_score, compare_to_market, log_loss
from forecasting.forecast import ProbabilisticForecast


NOW = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)


def forecast(probability_yes="0.7", baseline="0.55", abstain=False):
    return ProbabilisticForecast(
        forecast_id="f1",
        request_id="r1",
        condition_id="0xabc",
        provider="local",
        model="m1",
        probability_yes=probability_yes,
        uncertainty="0.1",
        abstain=abstain,
        issued_at=NOW,
        baseline_probability=baseline,
    )


def test_brier_score_rewards_better_probability():
    assert brier_score("0.8", True) < brier_score("0.55", True)


def test_log_loss_is_finite_at_probability_extremes():
    assert log_loss("1", True) >= 0
    assert log_loss("0", False) >= 0


def test_market_comparison_reports_positive_skill():
    result = compare_to_market(forecast("0.8", "0.55"), True)
    assert result.beats_market is True
    assert result.brier_skill_vs_market > 0


def test_abstaining_forecast_is_not_scored():
    with pytest.raises(ValueError):
        compare_to_market(forecast(abstain=True), True)
