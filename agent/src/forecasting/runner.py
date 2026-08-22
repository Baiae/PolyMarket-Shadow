"""Bounded forecasting experiment runner with append-only journaling."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .forecast import ForecastRequest, ProbabilisticForecast, utc_now
from .journal import ForecastJournal
from .provider import ForecastProvider


@dataclass(frozen=True, slots=True)
class ForecastFailure:
    provider: str
    model: str
    error: str


@dataclass(frozen=True, slots=True)
class ForecastRunResult:
    forecasts: tuple[ProbabilisticForecast, ...]
    failures: tuple[ForecastFailure, ...]


class ForecastExperiment:
    """Runs research forecasts only; it has no broker or risk-manager dependency."""

    def __init__(
        self,
        providers: list[ForecastProvider],
        journal: ForecastJournal,
    ):
        if not providers:
            raise ValueError("at least one forecast provider is required")
        keys = [(provider.provider_name, provider.model_name) for provider in providers]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate provider/model in forecast experiment")
        self.providers = tuple(providers)
        self.journal = journal

    async def run(self, request: ForecastRequest) -> ForecastRunResult:
        self.journal.record_request(request)
        raw_results = await asyncio.gather(
            *(provider.forecast(request) for provider in self.providers),
            return_exceptions=True,
        )
        forecasts: list[ProbabilisticForecast] = []
        failures: list[ForecastFailure] = []
        for provider, result in zip(self.providers, raw_results):
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result
                error = f"{type(result).__name__}: {result}"
                failure = ForecastFailure(
                    provider=provider.provider_name,
                    model=provider.model_name,
                    error=error,
                )
                self.journal.record_failure(
                    request,
                    provider=provider.provider_name,
                    model=provider.model_name,
                    error=error,
                    recorded_at=utc_now(),
                )
                failures.append(failure)
                continue
            self.journal.record_forecast(request, result)
            forecasts.append(result)
        return ForecastRunResult(tuple(forecasts), tuple(failures))
