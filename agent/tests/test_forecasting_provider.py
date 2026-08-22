from datetime import UTC, datetime

from forecasting.forecast import ForecastRequest, MarketBaseline
from forecasting.provider import OpenAICompatibleForecastProvider


NOW = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)


def request():
    return ForecastRequest.create(
        request_id="r1",
        condition_id="0xabc",
        question="Question?",
        baseline=MarketBaseline("0xabc", "0.62", NOW, "book"),
        issued_at=NOW,
    )


def test_provider_prompt_hides_market_baseline_by_default():
    prompt = OpenAICompatibleForecastProvider._prompt(
        request(),
        include_market_baseline=False,
    )
    assert "0.62" not in prompt
    assert "Market baseline at issuance" not in prompt


def test_provider_prompt_can_include_baseline_for_explicit_experiment():
    prompt = OpenAICompatibleForecastProvider._prompt(
        request(),
        include_market_baseline=True,
    )
    assert "Market baseline at issuance: 0.62" in prompt
