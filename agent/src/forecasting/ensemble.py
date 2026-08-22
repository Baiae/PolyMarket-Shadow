"""Skill-weighted forecast ensembles."""

from __future__ import annotations

from decimal import Decimal

from .forecast import ProbabilisticForecast

ZERO = Decimal(0)
ONE = Decimal(1)


def weights_from_brier_skill(
    forecaster_brier: dict[str, Decimal | str | float],
    *,
    market_brier: Decimal | str | float,
) -> dict[str, Decimal]:
    """Assign weight only to forecasters that beat the market baseline."""
    baseline = Decimal(str(market_brier))
    if baseline < ZERO:
        raise ValueError("market_brier must be non-negative")
    raw = {
        key: max(baseline - Decimal(str(score)), ZERO)
        for key, score in forecaster_brier.items()
    }
    total = sum(raw.values(), ZERO)
    if total <= ZERO:
        raise ValueError("no forecaster demonstrated positive Brier skill")
    return {key: value / total for key, value in raw.items() if value > ZERO}


class WeightedEnsemble:
    def __init__(self, weights: dict[str, Decimal | str | float]):
        parsed = {key: Decimal(str(value)) for key, value in weights.items()}
        if not parsed or any(value < ZERO for value in parsed.values()):
            raise ValueError("ensemble weights must be non-negative and non-empty")
        total = sum(parsed.values(), ZERO)
        if total <= ZERO:
            raise ValueError("ensemble weights must sum above zero")
        self.weights = {key: value / total for key, value in parsed.items()}

    def combine(
        self,
        forecasts: list[ProbabilisticForecast],
        *,
        forecast_id: str,
    ) -> ProbabilisticForecast:
        usable = [
            forecast
            for forecast in forecasts
            if not forecast.abstain and forecast.forecaster_key in self.weights
        ]
        if not usable:
            raise ValueError("no weighted non-abstaining forecasts")
        condition_ids = {forecast.condition_id for forecast in usable}
        request_ids = {forecast.request_id for forecast in usable}
        if len(condition_ids) != 1 or len(request_ids) != 1:
            raise ValueError("cannot ensemble forecasts from different requests")

        present_weights = {
            forecast.forecaster_key: self.weights[forecast.forecaster_key]
            for forecast in usable
        }
        total_weight = sum(present_weights.values(), ZERO)
        weighted_probability = sum(
            forecast.probability_yes * present_weights[forecast.forecaster_key]
            for forecast in usable
        ) / total_weight
        weighted_uncertainty = sum(
            forecast.uncertainty * present_weights[forecast.forecaster_key]
            for forecast in usable
        ) / total_weight
        baseline_values = {
            forecast.baseline_probability
            for forecast in usable
            if forecast.baseline_probability is not None
        }
        baseline = baseline_values.pop() if len(baseline_values) == 1 else None
        evidence_ids = tuple(
            dict.fromkeys(
                evidence_id
                for forecast in usable
                for evidence_id in forecast.evidence_ids
            )
        )
        issued_at = max(forecast.issued_at for forecast in usable)
        return ProbabilisticForecast(
            forecast_id=forecast_id,
            request_id=usable[0].request_id,
            condition_id=usable[0].condition_id,
            provider="ensemble",
            model="skill-weighted",
            probability_yes=weighted_probability,
            uncertainty=min(weighted_uncertainty, ONE),
            abstain=False,
            issued_at=issued_at,
            evidence_ids=evidence_ids,
            baseline_probability=baseline,
            metadata=(("members", str(len(usable))),),
        )
