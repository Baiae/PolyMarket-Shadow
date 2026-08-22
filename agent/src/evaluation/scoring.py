"""Proper scoring rules for binary probabilistic forecasts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from forecasting.forecast import ProbabilisticForecast, probability

ZERO = Decimal(0)
ONE = Decimal(1)
EPSILON = Decimal("1e-12")


def _outcome(value: bool | int) -> Decimal:
    if value is True or value == 1:
        return ONE
    if value is False or value == 0:
        return ZERO
    raise ValueError("binary outcome must be bool, 0, or 1")


def brier_score(probability_yes: Decimal | str | float, outcome_yes: bool | int) -> Decimal:
    p = probability(probability_yes)
    outcome = _outcome(outcome_yes)
    return (p - outcome) ** 2


def log_loss(probability_yes: Decimal | str | float, outcome_yes: bool | int) -> Decimal:
    p = probability(probability_yes)
    outcome = _outcome(outcome_yes)
    bounded = min(max(p, EPSILON), ONE - EPSILON)
    with localcontext() as context:
        context.prec = 28
        return -(outcome * bounded.ln() + (ONE - outcome) * (ONE - bounded).ln())


@dataclass(frozen=True, slots=True)
class ScoreComparison:
    forecast_id: str
    forecaster_key: str
    brier: Decimal
    log_loss: Decimal
    market_brier: Decimal
    market_log_loss: Decimal

    @property
    def brier_skill_vs_market(self) -> Decimal:
        return self.market_brier - self.brier

    @property
    def beats_market(self) -> bool:
        return self.brier < self.market_brier


def compare_to_market(
    forecast: ProbabilisticForecast,
    outcome_yes: bool | int,
) -> ScoreComparison:
    if forecast.abstain:
        raise ValueError("abstaining forecasts are not scored")
    if forecast.baseline_probability is None:
        raise ValueError("market baseline is required for comparison")
    return ScoreComparison(
        forecast_id=forecast.forecast_id,
        forecaster_key=forecast.forecaster_key,
        brier=brier_score(forecast.probability_yes, outcome_yes),
        log_loss=log_loss(forecast.probability_yes, outcome_yes),
        market_brier=brier_score(forecast.baseline_probability, outcome_yes),
        market_log_loss=log_loss(forecast.baseline_probability, outcome_yes),
    )
