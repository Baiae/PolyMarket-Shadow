from datetime import UTC, datetime

import aiohttp
import pytest

from forecasting.forecast import ForecastRequest, ProbabilisticForecast, make_forecast_id
from forecasting.journal import ForecastJournal
from forecasting.resolution import (
    ResolutionCapture,
    observe_resolution,
    unresolved_condition_ids,
)


NOW = datetime(2026, 8, 22, 20, 0, tzinfo=UTC)


def market_payload(condition_id, *, closed=True, yes=False, no=False):
    return {
        "condition_id": condition_id,
        "closed": closed,
        "tokens": [
            {"token_id": f"yes-{condition_id}", "outcome": "Yes", "winner": yes},
            {"token_id": f"no-{condition_id}", "outcome": "No", "winner": no},
        ],
    }


def request(condition_id, suffix):
    return ForecastRequest.create(
        request_id=f"request-{suffix}",
        condition_id=condition_id,
        question=f"Will {suffix} happen?",
        issued_at=NOW,
    )


def forecast_for(req):
    return ProbabilisticForecast(
        forecast_id=make_forecast_id(req.request_id, "local", "model-a"),
        request_id=req.request_id,
        condition_id=req.condition_id,
        provider="local",
        model="model-a",
        probability_yes="0.60",
        uncertainty="0.20",
        abstain=False,
        issued_at=req.issued_at,
    )


class FakeResolutionClient:
    base_url = "https://clob.example"

    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    async def fetch_market(self, condition_id):
        self.calls.append(condition_id)
        value = self.payloads[condition_id]
        if isinstance(value, Exception):
            raise value
        return value


def test_observe_resolution_requires_closed_market_and_exactly_one_winner():
    assert observe_resolution(
        market_payload("c1", closed=False, yes=True),
        expected_condition_id="c1",
        observed_at=NOW,
    ) is None
    assert observe_resolution(
        market_payload("c1"),
        expected_condition_id="c1",
        observed_at=NOW,
    ) is None

    observed = observe_resolution(
        market_payload("c1", yes=True),
        expected_condition_id="c1",
        observed_at=NOW,
    )
    assert observed is not None
    assert observed.outcome_yes is True
    assert observed.winning_outcome == "Yes"
    assert observed.winning_token_id == "yes-c1"

    with pytest.raises(ValueError, match="multiple winning"):
        observe_resolution(
            market_payload("c1", yes=True, no=True),
            expected_condition_id="c1",
            observed_at=NOW,
        )


def test_observe_resolution_rejects_identity_and_outcome_shape_errors():
    with pytest.raises(ValueError, match="condition_id mismatch"):
        observe_resolution(
            market_payload("other", yes=True),
            expected_condition_id="expected",
            observed_at=NOW,
        )

    malformed = market_payload("c1", yes=True)
    malformed["tokens"][0]["outcome"] = "Maybe"
    with pytest.raises(ValueError, match="unexpected binary outcome"):
        observe_resolution(malformed, expected_condition_id="c1", observed_at=NOW)


def test_unresolved_conditions_are_deduplicated_and_disappear_after_resolution():
    journal = ForecastJournal()
    first = request("c1", "one")
    second = request("c1", "two")
    other = request("c2", "three")
    journal.record_request(first)
    journal.record_request(second)
    journal.record_request(other)

    assert unresolved_condition_ids(journal, limit=10) == ("c1", "c2")
    journal.record_resolution(
        condition_id="c1",
        outcome_yes=True,
        resolved_at=NOW,
        resolution_id="resolution-c1",
    )
    assert unresolved_condition_ids(journal, limit=10) == ("c2",)
    with pytest.raises(ValueError, match="limit must be positive"):
        unresolved_condition_ids(journal, limit=0)


@pytest.mark.asyncio
async def test_capture_matures_forecast_and_skips_it_on_future_runs():
    journal = ForecastJournal()
    resolved_request = request("c1", "resolved")
    open_request = request("c2", "open")
    journal.record_forecast(resolved_request, forecast_for(resolved_request))
    journal.record_request(open_request)

    client = FakeResolutionClient(
        {
            "c1": market_payload("c1", yes=True),
            "c2": market_payload("c2", closed=False),
        }
    )
    capture = ResolutionCapture(journal, client=client, concurrency=2)
    summary = await capture.capture_once(limit=10)

    assert summary.checked == 2
    assert summary.newly_resolved == 1
    assert summary.unresolved == 1
    assert summary.failures == ()
    matured = journal.resolved_forecasts()
    assert len(matured) == 1
    assert matured[0][0].condition_id == "c1"
    assert matured[0][1] is True

    second = await capture.capture_once(limit=10)
    assert second.checked == 1
    assert client.calls.count("c1") == 1


@pytest.mark.asyncio
async def test_capture_isolates_external_failures():
    journal = ForecastJournal()
    journal.record_request(request("c1", "good"))
    journal.record_request(request("c2", "bad"))
    client = FakeResolutionClient(
        {
            "c1": market_payload("c1", no=True),
            "c2": aiohttp.ClientConnectionError("network unavailable"),
        }
    )
    summary = await ResolutionCapture(journal, client=client).capture_once(limit=10)
    assert summary.newly_resolved == 1
    assert len(summary.failures) == 1
    assert summary.failures[0].condition_id == "c2"
