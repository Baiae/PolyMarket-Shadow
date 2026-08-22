import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from evaluation.cohort import DEFAULT_POLICY, CohortManifest, ForecasterRef, load_cohort_attempts
from forecasting.forecast import EvidenceItem, ForecastRequest, MarketBaseline
from forecasting.journal import ForecastJournal


NOW = datetime(2026, 8, 22, 20, 0, tzinfo=UTC)
FORECASTER = ForecasterRef("local", "model-a")


def request(index: int, *, category: str, event_id: str, horizon_days: int) -> ForecastRequest:
    issued_at = NOW + timedelta(seconds=index)
    condition_id = f"condition-{index}"
    content = json.dumps(
        {"category": category, "event_id": event_id},
        sort_keys=True,
        separators=(",", ":"),
    )
    evidence = EvidenceItem.from_text(
        evidence_id=f"evidence-{index}",
        source="https://gamma-api.polymarket.com/markets",
        retrieved_at=issued_at,
        text=content,
        title="Polymarket Gamma market metadata",
    )
    baseline = MarketBaseline(
        condition_id=condition_id,
        probability_yes=Decimal("0.50"),
        captured_at=issued_at,
        source="https://clob.polymarket.com/books",
    )
    return ForecastRequest.create(
        request_id=f"request-{index}",
        condition_id=condition_id,
        question=f"Question {index}?",
        resolves_at=issued_at + timedelta(days=horizon_days),
        evidence=(evidence,),
        baseline=baseline,
        issued_at=issued_at,
    )


def test_preregistered_forecaster_is_expected_for_every_request_in_dedicated_journal():
    journal = ForecastJournal()
    failed = request(1, category="Politics", event_id="event-a", horizon_days=3)
    missing = request(2, category="Tech", event_id="event-b", horizon_days=14)
    journal.record_failure(
        failed,
        provider=FORECASTER.provider,
        model=FORECASTER.model,
        error="ClientConnectionError: unavailable",
        recorded_at=NOW + timedelta(minutes=1),
    )
    journal.record_request(missing)
    for index, item in enumerate((failed, missing), start=1):
        journal.record_resolution(
            condition_id=item.condition_id,
            outcome_yes=index % 2 == 0,
            resolved_at=NOW + timedelta(days=30),
            resolution_id=f"resolution-{index}",
        )

    manifest = CohortManifest(
        cohort_id="cohort-accounting",
        policy_id=DEFAULT_POLICY.policy_id,
        started_at=NOW - timedelta(minutes=1),
        forecasters=(FORECASTER,),
    )
    attempts = load_cohort_attempts(journal, manifest)

    assert len(attempts) == 2
    by_request = {item.request_id: item for item in attempts}
    assert by_request[failed.request_id].failure_error is not None
    assert by_request[failed.request_id].forecast_probability is None
    assert by_request[missing.request_id].failure_error is None
    assert by_request[missing.request_id].forecast_probability is None
    assert by_request[failed.request_id].category == "Politics"
    assert by_request[missing.request_id].horizon == "7-30d"
