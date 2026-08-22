"""Aggregate resolved forecast performance without hiding the market baseline."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from forecasting.forecast import ProbabilisticForecast

from .scoring import compare_to_market

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class ForecasterSummary:
    forecaster_key: str
    scored_count: int
    abstention_count: int
    mean_brier: Decimal
    mean_log_loss: Decimal
    mean_market_brier: Decimal
    mean_market_log_loss: Decimal

    @property
    def mean_brier_skill_vs_market(self) -> Decimal:
        return self.mean_market_brier - self.mean_brier

    @property
    def beats_market(self) -> bool:
        return self.mean_brier < self.mean_market_brier


def summarize_resolved(
    samples: list[tuple[ProbabilisticForecast, bool]],
) -> list[ForecasterSummary]:
    grouped: dict[str, list[tuple[ProbabilisticForecast, bool]]] = {}
    for forecast, outcome in samples:
        grouped.setdefault(forecast.forecaster_key, []).append((forecast, outcome))

    summaries: list[ForecasterSummary] = []
    for key, group in sorted(grouped.items()):
        abstentions = sum(1 for forecast, _ in group if forecast.abstain)
        comparisons = [
            compare_to_market(forecast, outcome)
            for forecast, outcome in group
            if not forecast.abstain and forecast.baseline_probability is not None
        ]
        if not comparisons:
            continue
        count = Decimal(len(comparisons))
        summaries.append(
            ForecasterSummary(
                forecaster_key=key,
                scored_count=len(comparisons),
                abstention_count=abstentions,
                mean_brier=sum((item.brier for item in comparisons), ZERO) / count,
                mean_log_loss=(
                    sum((item.log_loss for item in comparisons), ZERO) / count
                ),
                mean_market_brier=(
                    sum((item.market_brier for item in comparisons), ZERO) / count
                ),
                mean_market_log_loss=(
                    sum((item.market_log_loss for item in comparisons), ZERO) / count
                ),
            )
        )
    return summaries
