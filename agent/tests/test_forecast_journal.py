from datetime import UTC, datetime
from pathlib import Path

import pytest

from forecasting.forecast import (
    EvidenceItem,
    ForecastRequest,
    MarketBaseline,
    ProbabilisticForecast,
)
from forecasting.journal import ForecastJournal


NOW = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)


def pair():
    evidence = EvidenceItem.from_text(
        evidence_id="e1",
        source="source",
        retrieved_at=NOW,
        text="evidence",
    )
    baseline = MarketBaseline("0xabc", "0.55", NOW, "book")
    request = ForecastRequest.create(
        request_id="r1",
        condition_id="0xabc",
        question="Question?",
        evidence=[evidence],
        baseline=baseline,
        issued_at=NOW,
    )
    forecast = ProbabilisticForecast(
        forecast_id="f1",
        request_id="r1",
        condition_id="0xabc",
        provider="local",
        model="m1",
        probability_yes="0.7",
        uncertainty="0.2",
        abstain=False,
        issued_at=NOW,
        evidence_ids=("e1",),
        baseline_probability="0.55",
    )
    return request, forecast


def test_forecast_and_resolution_are_restart_safe(tmp_path: Path):
    path = tmp_path / "forecasting.db"
    request, forecast = pair()

    first = ForecastJournal(str(path))
    assert first.record_forecast(request, forecast) is True
    assert first.record_forecast(request, forecast) is False
    assert first.record_resolution(
        condition_id="0xabc",
        outcome_yes=True,
        resolved_at=NOW,
        resolution_id="resolution-1",
    ) is True
    first.close()

    second = ForecastJournal(str(path))
    resolved = second.resolved_forecasts()
    assert len(resolved) == 1
    assert resolved[0][0].probability_yes == forecast.probability_yes
    assert resolved[0][1] is True
    assert second.record_forecast(request, forecast) is False
    second.close()


def test_evidence_identifier_cannot_change_provenance():
    request, forecast = pair()
    journal = ForecastJournal()
    journal.record_forecast(request, forecast)

    changed = EvidenceItem.from_text(
        evidence_id="e1",
        source="different-source",
        retrieved_at=NOW,
        text="different evidence",
    )
    changed_request = ForecastRequest.create(
        request_id="r2",
        condition_id="0xabc",
        question="Question?",
        evidence=[changed],
        baseline=request.baseline,
        issued_at=NOW,
    )
    changed_forecast = ProbabilisticForecast(
        forecast_id="f2",
        request_id="r2",
        condition_id="0xabc",
        provider="local",
        model="m1",
        probability_yes="0.6",
        uncertainty="0.2",
        abstain=False,
        issued_at=NOW,
        evidence_ids=("e1",),
        baseline_probability="0.55",
    )
    with pytest.raises(ValueError):
        journal.record_forecast(changed_request, changed_forecast)
