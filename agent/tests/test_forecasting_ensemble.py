from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forecasting.ensemble import WeightedEnsemble, weights_from_brier_skill
from forecasting.forecast import ProbabilisticForecast


NOW = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)


def forecast(provider, model, p, *, abstain=False):
    return ProbabilisticForecast(
        forecast_id=f"{provider}-{model}",
        request_id="r1",
        condition_id="0xabc",
        provider=provider,
        model=model,
        probability_yes=p,
        uncertainty="0.2",
        abstain=abstain,
        issued_at=NOW,
        baseline_probability="0.5",
    )


def test_weights_are_earned_only_by_beating_market_brier():
    weights = weights_from_brier_skill(
        {"a:m1": Decimal("0.10"), "b:m2": Decimal("0.30")},
        market_brier=Decimal("0.25"),
    )
    assert weights == {"a:m1": Decimal("1")}


def test_weights_reject_when_no_forecaster_beats_market():
    with pytest.raises(ValueError):
        weights_from_brier_skill({"a:m1": "0.3"}, market_brier="0.25")


def test_weighted_ensemble_ignores_abstainers_and_vote_counts():
    ensemble = WeightedEnsemble({"a:m1": "0.75", "b:m2": "0.25"})
    combined = ensemble.combine(
        [
            forecast("a", "m1", "0.8"),
            forecast("b", "m2", "0.2", abstain=True),
        ],
        forecast_id="ensemble-1",
    )
    assert combined.probability_yes == Decimal("0.8")
    assert combined.provider == "ensemble"
