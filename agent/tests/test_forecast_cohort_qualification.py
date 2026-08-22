import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from evaluation.cohort import (
    DEFAULT_POLICY,
    CohortAttempt,
    CohortManifest,
    ForecasterRef,
    QualificationPolicy,
    qualify_cohort,
    qualify_forecaster,
)
from forecasting.forecast import (
    EvidenceItem,
    ForecastRequest,
    MarketBaseline,
    ProbabilisticForecast,
    make_forecast_id,
)
from forecasting.journal import ForecastJournal


NOW = datetime(2026, 8, 22, 20, 0, tzinfo=UTC)
FORECASTER = ForecasterRef("local", "model-a")


def manifest() -> CohortManifest:
    return CohortManifest(
        cohort_id="cohort-v1",
        policy_id=DEFAULT_POLICY.policy_id,
        started_at=NOW - timedelta(minutes=1),
        forecasters=(FORECASTER,),
        dedicated_journal=True,
    )


def make_request(
    index: int,
    *,
    condition_id: str | None = None,
    issued_at: datetime | None = None,
    category: str = "Politics",
    event_id: str = "event-1",
    horizon_days: int = 14,
    baseline: str = "0.55",
) -> ForecastRequest:
    issued = issued_at or (NOW + timedelta(seconds=index))
    condition = condition_id or f"condition-{index}"
    metadata_text = json.dumps(
        {
            "category": category,
            "condition_id": condition,
            "event_id": event_id,
            "gamma_market_id": f"gamma-{index}",
            "question": f"Question {index}?",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    evidence = EvidenceItem.from_text(
        evidence_id=f"gamma-evidence-{index}",
        source="https://gamma-api.polymarket.com/markets",
        retrieved_at=issued,
        text=metadata_text,
        title="Polymarket Gamma market metadata",
    )
    market_baseline = MarketBaseline(
        condition_id=condition,
        probability_yes=Decimal(baseline),
        captured_at=issued,
        source="https://clob.polymarket.com/books",
    )
    return ForecastRequest.create(
        request_id=f"request-{index}",
        condition_id=condition,
        question=f"Question {index}?",
        resolves_at=issued + timedelta(days=horizon_days),
        evidence=(evidence,),
        baseline=market_baseline,
        issued_at=issued,
    )


def make_forecast(request: ForecastRequest, probability_yes: str) -> ProbabilisticForecast:
    return ProbabilisticForecast(
        forecast_id=make_forecast_id(
            request.request_id,
            FORECASTER.provider,
            FORECASTER.model,
        ),
        request_id=request.request_id,
        condition_id=request.condition_id,
        provider=FORECASTER.provider,
        model=FORECASTER.model,
        probability_yes=probability_yes,
        uncertainty="0.10",
        abstain=False,
        issued_at=request.issued_at,
        evidence_ids=tuple(item.evidence_id for item in request.evidence),
        baseline_probability=request.baseline.probability_yes,
    )


def record_scored_case(
    journal: ForecastJournal,
    index: int,
    *,
    outcome_yes: bool,
    category: str,
    event_id: str,
    horizon_days: int,
) -> None:
    request = make_request(
        index,
        category=category,
        event_id=event_id,
        horizon_days=horizon_days,
    )
    forecast = make_forecast(request, "0.95" if outcome_yes else "0.05")
    journal.record_forecast(request, forecast)
    journal.record_resolution(
        condition_id=request.condition_id,
        outcome_yes=outcome_yes,
        resolved_at=NOW + timedelta(days=200),
        resolution_id=f"resolution-{index}",
    )


def test_manifest_is_hashed_and_requires_dedicated_unique_forecasters():
    cohort = manifest()
    assert len(cohort.sha256) == 64
    assert CohortManifest.from_mapping(cohort.as_mapping()) == cohort

    with pytest.raises(ValueError, match="dedicated journal"):
        CohortManifest(
            cohort_id="bad",
            policy_id=DEFAULT_POLICY.policy_id,
            started_at=NOW,
            forecasters=(FORECASTER,),
            dedicated_journal=False,
        )
    with pytest.raises(ValueError, match="unique"):
        CohortManifest(
            cohort_id="bad",
            policy_id=DEFAULT_POLICY.policy_id,
            started_at=NOW,
            forecasters=(FORECASTER, FORECASTER),
        )


def test_first_attempt_per_condition_is_canonical_and_retry_cannot_improve_score():
    journal = ForecastJournal()
    first = make_request(1, condition_id="same-condition", issued_at=NOW)
    second = make_request(
        2,
        condition_id="same-condition",
        issued_at=NOW + timedelta(hours=1),
    )
    journal.record_forecast(first, make_forecast(first, "0.10"))
    journal.record_forecast(second, make_forecast(second, "0.99"))
    journal.record_resolution(
        condition_id="same-condition",
        outcome_yes=True,
        resolved_at=NOW + timedelta(days=30),
        resolution_id="same-resolution",
    )

    report = qualify_cohort(journal, manifest())
    result = report.forecasters[0]
    assert result.scored_count == 1
    assert result.repeat_attempts_excluded == 1
    assert result.mean_brier == Decimal("0.81")
    assert result.status == "COLLECTING"


def test_default_policy_can_qualify_strong_diverse_out_of_sample_cohort():
    journal = ForecastJournal()
    categories = ("Politics", "Economics", "Tech", "Culture")
    horizons = (1, 3, 14)
    for index in range(120):
        record_scored_case(
            journal,
            index,
            outcome_yes=index % 2 == 0,
            category=categories[index % len(categories)],
            event_id=f"event-{index // 2}",
            horizon_days=horizons[index % len(horizons)],
        )

    report = qualify_cohort(journal, manifest())
    result = report.forecasters[0]

    assert result.status == "ELIGIBLE_FOR_PAPER_PROPOSAL"
    assert result.resolved_conditions == 120
    assert result.resolved_event_clusters == 60
    assert result.scored_count == 120
    assert result.coverage == Decimal("1")
    assert result.mean_brier_skill_vs_market is not None
    assert result.mean_brier_skill_vs_market > 0
    assert result.brier_skill_interval is not None
    assert result.brier_skill_interval.lower > 0
    assert result.expected_calibration_error is not None
    assert result.expected_calibration_error <= DEFAULT_POLICY.max_ece
    assert len(
        [item for item in result.category_slices if item.scored_count >= 10]
    ) >= 3
    assert len(
        [item for item in result.horizon_slices if item.scored_count >= 10]
    ) >= 2
    assert all(gate.state == "PASS" for gate in result.gates)


def test_coverage_failure_blocks_paper_proposal_after_evidence_is_ready():
    policy = QualificationPolicy(
        policy_id="test-policy",
        min_resolved_conditions=4,
        min_resolved_event_clusters=2,
        min_scored=3,
        min_coverage=Decimal("0.80"),
        confidence_level=Decimal("0.90"),
        bootstrap_iterations=100,
        max_ece=Decimal("0.20"),
        min_category_slices=1,
        min_horizon_slices=1,
        min_slice_scored=1,
        max_slice_skill_deficit=Decimal("0.10"),
    )
    attempts = [
        CohortAttempt(
            request_id=f"request-{index}",
            condition_id=f"condition-{index}",
            event_id=f"event-{index // 2}",
            category="Politics",
            horizon="1-7d",
            issued_at=NOW + timedelta(seconds=index),
            forecaster_key=FORECASTER.key,
            outcome_yes=True,
            baseline_probability=Decimal("0.55"),
            forecast_probability=(Decimal("0.90") if index < 3 else None),
            abstain=False,
            failure_error=("provider unavailable" if index == 3 else None),
            integrity_error=None,
        )
        for index in range(4)
    ]

    result = qualify_forecaster(FORECASTER.key, attempts, policy=policy)
    assert result.scored_count == 3
    assert result.provider_failure_count == 1
    assert result.coverage == Decimal("0.75")
    assert result.status == "NOT_QUALIFIED"
    coverage_gate = next(gate for gate in result.gates if gate.name == "coverage")
    assert coverage_gate.state == "FAIL"


def test_missing_provider_result_counts_as_incomplete_not_abstention():
    policy = QualificationPolicy(
        policy_id="test-policy",
        min_resolved_conditions=1,
        min_resolved_event_clusters=1,
        min_scored=1,
        bootstrap_iterations=10,
        min_category_slices=1,
        min_horizon_slices=1,
        min_slice_scored=1,
    )
    attempt = CohortAttempt(
        request_id="request-missing",
        condition_id="condition-missing",
        event_id="event-missing",
        category="Tech",
        horizon="7-30d",
        issued_at=NOW,
        forecaster_key=FORECASTER.key,
        outcome_yes=False,
        baseline_probability=Decimal("0.40"),
        forecast_probability=None,
        abstain=False,
        failure_error=None,
        integrity_error=None,
    )
    result = qualify_forecaster(FORECASTER.key, [attempt], policy=policy)
    assert result.incomplete_count == 1
    assert result.abstention_count == 0
    assert result.coverage == 0
    assert result.status == "COLLECTING"
