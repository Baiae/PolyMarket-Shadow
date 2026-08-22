from datetime import UTC, datetime

import pytest

from forecasting.forecast import ForecastRequest, ProbabilisticForecast, make_forecast_id
from forecasting.journal import ForecastJournal
from forecasting.runner import ForecastExperiment


NOW = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)


class FakeProvider:
    def __init__(self, provider_name, model_name, p):
        self.provider_name = provider_name
        self.model_name = model_name
        self.p = p

    async def forecast(self, request):
        return ProbabilisticForecast(
            forecast_id=make_forecast_id(
                request.request_id,
                self.provider_name,
                self.model_name,
            ),
            request_id=request.request_id,
            condition_id=request.condition_id,
            provider=self.provider_name,
            model=self.model_name,
            probability_yes=self.p,
            uncertainty="0.2",
            abstain=False,
            issued_at=request.issued_at,
        )


class FailingProvider(FakeProvider):
    async def forecast(self, request):
        raise RuntimeError("provider unavailable")


@pytest.mark.asyncio
async def test_experiment_records_success_and_isolates_provider_failure():
    journal = ForecastJournal()
    experiment = ForecastExperiment(
        [
            FakeProvider("local", "a", "0.6"),
            FailingProvider("remote", "b", "0.5"),
        ],
        journal,
    )
    request = ForecastRequest.create(
        request_id="r1",
        condition_id="0xabc",
        question="Question?",
        issued_at=NOW,
    )
    result = await experiment.run(request)
    assert len(result.forecasts) == 1
    assert len(result.failures) == 1
    assert result.failures[0].provider == "remote"
