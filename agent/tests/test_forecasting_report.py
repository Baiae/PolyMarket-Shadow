from datetime import UTC, datetime

from evaluation.report import summarize_resolved
from forecasting.forecast import ProbabilisticForecast


NOW = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)


def item(forecast_id, probability_yes, baseline, outcome):
    forecast = ProbabilisticForecast(
        forecast_id=forecast_id,
        request_id=f"request-{forecast_id}",
        condition_id=f"condition-{forecast_id}",
        provider="local",
        model="m1",
        probability_yes=probability_yes,
        uncertainty="0.2",
        abstain=False,
        issued_at=NOW,
        baseline_probability=baseline,
    )
    return forecast, outcome


def test_summary_keeps_market_baseline_visible():
    summaries = summarize_resolved(
        [
            item("f1", "0.8", "0.6", True),
            item("f2", "0.2", "0.4", False),
        ]
    )
    assert len(summaries) == 1
    assert summaries[0].scored_count == 2
    assert summaries[0].beats_market is True
    assert summaries[0].mean_brier_skill_vs_market > 0
