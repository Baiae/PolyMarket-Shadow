from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from forecasting.forecast import ForecastRequest, MarketBaseline
from forecasting.provider import OpenAICompatibleForecastProvider


NOW = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)


class FakeCompletions:
    def __init__(self, content):
        self.content = content

    async def create(self, **_kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FakeClient:
    def __init__(self, content):
        self.chat = SimpleNamespace(completions=FakeCompletions(content))


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


@pytest.mark.asyncio
async def test_provider_parses_explicit_probability_json():
    provider = OpenAICompatibleForecastProvider(
        provider_name="local",
        model_name="model-a",
        api_key="unused",
        base_url="http://127.0.0.1:1234/v1",
        client=FakeClient(
            '{"probability_yes":0.73,"uncertainty":0.18,'
            '"abstain":false,"rationale":"bounded evidence"}'
        ),
    )
    result = await provider.forecast(request())
    assert str(result.probability_yes) == "0.73"
    assert str(result.uncertainty) == "0.18"
    assert result.baseline_probability == MarketBaseline(
        "0xabc", "0.62", NOW, "book"
    ).probability_yes
    assert result.provider == "local"
