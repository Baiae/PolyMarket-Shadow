import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from collect_forecasts import CohortGammaAdapter  # noqa: E402
from domain.market import MarketIdentity  # noqa: E402
from evaluation.cohort import CohortManifest, ForecasterRef  # noqa: E402
from evaluation.cohort_protocol import (  # noqa: E402
    DECISION_CONDITION_COUNT,
    FIXED_POLICY,
    MAX_RESOLUTION_HORIZON_DAYS,
    QualificationManifest,
    canonical_json_sha256,
    forecast_protocol_sha256,
    policy_sha256,
    qualify_fixed_cohort,
)
from forecasting.forecast import (  # noqa: E402
    EvidenceItem,
    ForecastRequest,
    MarketBaseline,
    ProbabilisticForecast,
    make_forecast_id,
)
from forecasting.journal import ForecastJournal  # noqa: E402


NOW = datetime(2026, 8, 22, 20, 0, tzinfo=UTC)
FORECASTER = ForecasterRef("local", "model-a")


def qualification_manifest() -> QualificationManifest:
    cohort = CohortManifest(
        cohort_id="fixed-cohort",
        policy_id=FIXED_POLICY.policy_id,
        started_at=NOW - timedelta(minutes=1),
        forecasters=(FORECASTER,),
    )
    return QualificationManifest(
        cohort=cohort,
        provider_config_sha256="a" * 64,
        evidence_manifest_sha256="b" * 64,
        policy_sha256=policy_sha256(),
        forecast_protocol_sha256=forecast_protocol_sha256(),
    )


def request(index: int, *, category: str, event_id: str, horizon_days: int):
    issued_at = NOW + timedelta(seconds=index)
    condition_id = f"condition-{index}"
    metadata = EvidenceItem.from_text(
        evidence_id=f"metadata-{index}",
        source="https://gamma-api.polymarket.com/markets",
        retrieved_at=issued_at,
        text=json.dumps(
            {
                "category": category,
                "condition_id": condition_id,
                "event_id": event_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        title="Polymarket Gamma market metadata",
    )
    baseline = MarketBaseline(
        condition_id=condition_id,
        probability_yes=Decimal("0.55"),
        captured_at=issued_at,
        source="https://clob.polymarket.com/books",
    )
    return ForecastRequest.create(
        request_id=f"request-{index}",
        condition_id=condition_id,
        question=f"Question {index}?",
        resolves_at=issued_at + timedelta(days=horizon_days),
        evidence=(metadata,),
        baseline=baseline,
        issued_at=issued_at,
    )


def add_strong_case(
    journal: ForecastJournal,
    index: int,
    *,
    category: str,
    event_id: str,
    horizon_days: int,
):
    req = request(
        index,
        category=category,
        event_id=event_id,
        horizon_days=horizon_days,
    )
    outcome_yes = index % 2 == 0
    forecast = ProbabilisticForecast(
        forecast_id=make_forecast_id(
            req.request_id,
            FORECASTER.provider,
            FORECASTER.model,
        ),
        request_id=req.request_id,
        condition_id=req.condition_id,
        provider=FORECASTER.provider,
        model=FORECASTER.model,
        probability_yes="0.95" if outcome_yes else "0.05",
        uncertainty="0.10",
        abstain=False,
        issued_at=req.issued_at,
        evidence_ids=tuple(item.evidence_id for item in req.evidence),
        baseline_probability=req.baseline.probability_yes,
    )
    journal.record_forecast(req, forecast)
    journal.record_resolution(
        condition_id=req.condition_id,
        outcome_yes=outcome_yes,
        resolved_at=NOW + timedelta(days=100),
        resolution_id=f"resolution-{index}",
    )


def test_json_hash_is_semantic_and_manifest_detects_config_drift(tmp_path):
    providers = tmp_path / "providers.json"
    equivalent = tmp_path / "equivalent.json"
    evidence = tmp_path / "evidence.json"
    providers.write_text(
        '[{"provider_name":"local","model_name":"m","base_url":"http://127.0.0.1/v1","api_key_env":"KEY","api_key_required":false}]',
        encoding="utf-8",
    )
    equivalent.write_text(
        json.dumps(
            [
                {
                    "model_name": "m",
                    "provider_name": "local",
                    "api_key_required": False,
                    "api_key_env": "KEY",
                    "base_url": "http://127.0.0.1/v1",
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    evidence.write_text(
        json.dumps({"markets": {"*": [{"source": "operator:test", "content": "fact"}]}}),
        encoding="utf-8",
    )
    assert canonical_json_sha256(providers) == canonical_json_sha256(equivalent)

    base = qualification_manifest()
    manifest = QualificationManifest(
        cohort=base.cohort,
        provider_config_sha256=canonical_json_sha256(providers),
        evidence_manifest_sha256=canonical_json_sha256(evidence),
        policy_sha256=policy_sha256(),
        forecast_protocol_sha256=forecast_protocol_sha256(),
    )
    manifest.validate_files(providers=equivalent, evidence=evidence)

    equivalent.write_text(
        '[{"provider_name":"local","model_name":"changed","base_url":"http://127.0.0.1/v1","api_key_env":"KEY","api_key_required":false}]',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="provider configuration changed"):
        manifest.validate_files(providers=equivalent, evidence=evidence)


def test_fixed_decision_waits_for_all_120_then_can_become_eligible():
    journal = ForecastJournal()
    categories = ("Politics", "Economics", "Tech", "Culture")
    horizons = (1, 3, 14)
    for index in range(DECISION_CONDITION_COUNT - 1):
        add_strong_case(
            journal,
            index,
            category=categories[index % len(categories)],
            event_id=f"event-{index // 2}",
            horizon_days=horizons[index % len(horizons)],
        )
    before = qualify_fixed_cohort(journal, qualification_manifest()).forecasters[0]
    assert before.status == "COLLECTING"
    assert before.resolved_conditions == DECISION_CONDITION_COUNT - 1

    index = DECISION_CONDITION_COUNT - 1
    add_strong_case(
        journal,
        index,
        category=categories[index % len(categories)],
        event_id=f"event-{index // 2}",
        horizon_days=horizons[index % len(horizons)],
    )
    after = qualify_fixed_cohort(journal, qualification_manifest()).forecasters[0]
    assert after.resolved_conditions == DECISION_CONDITION_COUNT
    assert after.resolved_event_clusters == 60
    assert after.scored_count == 120
    assert after.status == "ELIGIBLE_FOR_PAPER_PROPOSAL"
    assert all(gate.state == "PASS" for gate in after.gates)


def test_fixed_decision_terminalizes_unmet_diversity_after_all_conditions_resolve():
    journal = ForecastJournal()
    for index in range(DECISION_CONDITION_COUNT):
        add_strong_case(
            journal,
            index,
            category="Politics",
            event_id=f"event-{index // 2}",
            horizon_days=14,
        )
    result = qualify_fixed_cohort(journal, qualification_manifest()).forecasters[0]
    assert result.status == "NOT_QUALIFIED"
    category_gate = next(
        gate for gate in result.gates if gate.name == "category_diversity"
    )
    horizon_gate = next(
        gate for gate in result.gates if gate.name == "horizon_diversity"
    )
    assert category_gate.state == "FAIL"
    assert horizon_gate.state == "FAIL"


class FakeGamma:
    base_url = "https://gamma.example"

    def __init__(self, markets):
        self.markets = markets

    async def fetch_active_markets(self, *, limit):
        return self.markets[:limit]


def market(condition_id: str, end_date: datetime) -> MarketIdentity:
    return MarketIdentity(
        gamma_market_id=f"gamma-{condition_id}",
        condition_id=condition_id,
        yes_token_id=f"yes-{condition_id}",
        no_token_id=f"no-{condition_id}",
        question=f"Question {condition_id}?",
        slug=f"slug-{condition_id}",
        end_date=end_date.isoformat(),
    )


@pytest.mark.asyncio
async def test_cohort_discovery_excludes_seen_and_beyond_90_day_horizon():
    now = datetime.now(UTC)
    seen = market("seen", now + timedelta(days=10))
    near = market("near", now + timedelta(days=30))
    far = market("far", now + timedelta(days=MAX_RESOLUTION_HORIZON_DAYS + 10))
    adapter = CohortGammaAdapter(
        FakeGamma([seen, near, far]),
        excluded_condition_ids={"seen"},
        max_horizon_days=MAX_RESOLUTION_HORIZON_DAYS,
    )
    result = await adapter.fetch_active_markets(limit=10)
    assert [item.condition_id for item in result] == ["near"]
