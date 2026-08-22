import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forecasting.forecast import (
    EvidenceItem,
    ForecastRequest,
    MarketBaseline,
    ProbabilisticForecast,
)


NOW = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)


def test_evidence_hash_and_request_provenance():
    evidence = EvidenceItem.from_text(
        evidence_id="e1",
        source="https://example.test/report",
        retrieved_at=NOW,
        text="source text",
        title="Report",
    )
    assert evidence.content_sha256 == hashlib.sha256(b"source text").hexdigest()
    baseline = MarketBaseline("0xabc", Decimal("0.55"), NOW, "book")
    request = ForecastRequest.create(
        request_id="r1",
        condition_id="0xabc",
        question="Will the event resolve YES?",
        evidence=[evidence],
        baseline=baseline,
        issued_at=NOW,
    )
    assert request.evidence[0].evidence_id == "e1"
    assert request.baseline.probability_yes == Decimal("0.55")


def test_request_rejects_future_evidence_to_prevent_leakage():
    evidence = EvidenceItem.from_text(
        evidence_id="e1",
        source="source",
        retrieved_at=NOW + timedelta(seconds=1),
        text="future evidence",
    )
    with pytest.raises(ValueError):
        ForecastRequest.create(
            request_id="r1",
            condition_id="0xabc",
            question="Question?",
            evidence=[evidence],
            issued_at=NOW,
        )


def test_forecast_probability_and_uncertainty_are_bounded():
    with pytest.raises(ValueError):
        ProbabilisticForecast(
            forecast_id="f1",
            request_id="r1",
            condition_id="0xabc",
            provider="local",
            model="model",
            probability_yes="1.1",
            uncertainty="0.2",
            abstain=False,
            issued_at=NOW,
        )


def test_request_rejects_baseline_from_another_market():
    baseline = MarketBaseline("0xother", Decimal("0.5"), NOW, "book")
    with pytest.raises(ValueError):
        ForecastRequest.create(
            request_id="r1",
            condition_id="0xabc",
            question="Question?",
            baseline=baseline,
            issued_at=NOW,
        )
