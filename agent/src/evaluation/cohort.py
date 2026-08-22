"""Pre-registered out-of-sample cohort qualification against the market baseline."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from forecasting.journal import ForecastJournal

from .calibration import expected_calibration_error, reliability_bins
from .scoring import brier_score, log_loss

ZERO = Decimal(0)
ONE = Decimal(1)
UNKNOWN_EVENT = "__unknown_event__"
UNKNOWN_CATEGORY = "Unknown"


@dataclass(frozen=True, slots=True)
class ForecasterRef:
    provider: str
    model: str

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model.strip():
            raise ValueError("provider and model are required")

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True, slots=True)
class CohortManifest:
    cohort_id: str
    policy_id: str
    started_at: datetime
    forecasters: tuple[ForecasterRef, ...]
    dedicated_journal: bool = True

    def __post_init__(self) -> None:
        if not self.cohort_id.strip():
            raise ValueError("cohort_id is required")
        if not self.policy_id.strip():
            raise ValueError("policy_id is required")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("cohort started_at must be timezone-aware")
        if not self.forecasters:
            raise ValueError("cohort requires at least one forecaster")
        keys = [item.key for item in self.forecasters]
        if len(keys) != len(set(keys)):
            raise ValueError("cohort forecasters must be unique")
        if self.dedicated_journal is not True:
            raise ValueError("qualification cohorts require a dedicated journal")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> CohortManifest:
        forecasters = payload.get("forecasters")
        if not isinstance(forecasters, Sequence) or isinstance(
            forecasters, (str, bytes)
        ):
            raise TypeError("cohort forecasters must be an array")
        parsed_forecasters: list[ForecasterRef] = []
        for item in forecasters:
            if not isinstance(item, Mapping):
                raise TypeError("cohort forecaster entries must be objects")
            parsed_forecasters.append(
                ForecasterRef(
                    provider=str(item.get("provider") or "").strip(),
                    model=str(item.get("model") or "").strip(),
                )
            )
        started_at = _parse_datetime(str(payload.get("started_at") or ""))
        return cls(
            cohort_id=str(payload.get("cohort_id") or "").strip(),
            policy_id=str(payload.get("policy_id") or "").strip(),
            started_at=started_at,
            forecasters=tuple(parsed_forecasters),
            dedicated_journal=payload.get("dedicated_journal") is True,
        )

    @classmethod
    def from_path(cls, path: Path) -> CohortManifest:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise TypeError("cohort manifest must be a JSON object")
        return cls.from_mapping(payload)

    def as_mapping(self) -> dict[str, Any]:
        return {
            "cohort_id": self.cohort_id,
            "policy_id": self.policy_id,
            "started_at": self.started_at.astimezone(UTC).isoformat(),
            "dedicated_journal": self.dedicated_journal,
            "forecasters": [
                {"provider": item.provider, "model": item.model}
                for item in self.forecasters
            ],
        }

    @property
    def sha256(self) -> str:
        raw = json.dumps(
            self.as_mapping(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class QualificationPolicy:
    policy_id: str = "PS-FQ-1"
    min_resolved_conditions: int = 100
    min_resolved_event_clusters: int = 50
    min_scored: int = 80
    min_coverage: Decimal = Decimal("0.80")
    confidence_level: Decimal = Decimal("0.95")
    bootstrap_iterations: int = 2000
    max_ece: Decimal = Decimal("0.10")
    min_category_slices: int = 3
    min_horizon_slices: int = 2
    min_slice_scored: int = 10
    max_slice_skill_deficit: Decimal = Decimal("0.02")

    def __post_init__(self) -> None:
        positive_ints = (
            self.min_resolved_conditions,
            self.min_resolved_event_clusters,
            self.min_scored,
            self.bootstrap_iterations,
            self.min_category_slices,
            self.min_horizon_slices,
            self.min_slice_scored,
        )
        if any(value < 1 for value in positive_ints):
            raise ValueError("qualification integer thresholds must be positive")
        if self.min_coverage < ZERO or self.min_coverage > ONE:
            raise ValueError("min_coverage must be in [0,1]")
        if self.confidence_level <= ZERO or self.confidence_level >= ONE:
            raise ValueError("confidence_level must be in (0,1)")
        if self.max_ece < ZERO or self.max_ece > ONE:
            raise ValueError("max_ece must be in [0,1]")
        if self.max_slice_skill_deficit < ZERO:
            raise ValueError("max_slice_skill_deficit cannot be negative")


DEFAULT_POLICY = QualificationPolicy()


@dataclass(frozen=True, slots=True)
class CohortAttempt:
    request_id: str
    condition_id: str
    event_id: str
    category: str
    horizon: str
    issued_at: datetime
    forecaster_key: str
    outcome_yes: bool | None
    baseline_probability: Decimal | None
    forecast_probability: Decimal | None
    abstain: bool
    failure_error: str | None
    integrity_error: str | None

    @property
    def event_cluster(self) -> str:
        return self.event_id or UNKNOWN_EVENT

    @property
    def resolved(self) -> bool:
        return self.outcome_yes is not None

    @property
    def scored(self) -> bool:
        return (
            self.resolved
            and self.forecast_probability is not None
            and self.baseline_probability is not None
            and not self.abstain
            and self.failure_error is None
            and self.integrity_error is None
        )


@dataclass(frozen=True, slots=True)
class SkillInterval:
    lower: Decimal
    upper: Decimal


@dataclass(frozen=True, slots=True)
class SliceSummary:
    label: str
    resolved_conditions: int
    scored_count: int
    abstention_count: int
    provider_failure_count: int
    incomplete_count: int
    coverage: Decimal
    mean_brier_skill_vs_market: Decimal | None


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    state: str
    observed: str
    required: str


@dataclass(frozen=True, slots=True)
class ForecasterQualification:
    forecaster_key: str
    status: str
    total_conditions: int
    resolved_conditions: int
    resolved_event_clusters: int
    unresolved_conditions: int
    repeat_attempts_excluded: int
    scored_count: int
    abstention_count: int
    provider_failure_count: int
    incomplete_count: int
    coverage: Decimal
    mean_brier: Decimal | None
    mean_market_brier: Decimal | None
    mean_brier_skill_vs_market: Decimal | None
    brier_skill_interval: SkillInterval | None
    mean_log_loss: Decimal | None
    mean_market_log_loss: Decimal | None
    mean_log_loss_skill_vs_market: Decimal | None
    log_loss_skill_interval: SkillInterval | None
    expected_calibration_error: Decimal | None
    category_slices: tuple[SliceSummary, ...]
    horizon_slices: tuple[SliceSummary, ...]
    gates: tuple[GateResult, ...]
    integrity_errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CohortQualificationReport:
    cohort_id: str
    policy_id: str
    manifest_sha256: str
    started_at: datetime
    request_count: int
    unique_condition_count: int
    forecasters: tuple[ForecasterQualification, ...]


def _parse_datetime(value: str) -> datetime:
    value = value.strip()
    if not value:
        raise ValueError("timestamp is required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _optional_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    return _parse_datetime(text) if text else None


def horizon_bucket(issued_at: datetime, resolves_at: datetime | None) -> str:
    if resolves_at is None:
        return "Unknown"
    delta = resolves_at - issued_at
    if delta <= timedelta(0):
        return "Invalid"
    if delta <= timedelta(days=1):
        return "<=1d"
    if delta <= timedelta(days=7):
        return "1-7d"
    if delta <= timedelta(days=30):
        return "7-30d"
    if delta <= timedelta(days=90):
        return "30-90d"
    return ">90d"


def _request_market_metadata(
    journal: ForecastJournal,
    *,
    started_at: datetime,
) -> dict[str, tuple[str, str]]:
    rows = journal.connection.execute(
        """
        SELECT re.request_id, e.title, e.content, re.ordinal
        FROM request_evidence AS re
        JOIN evidence AS e USING (evidence_id)
        JOIN requests AS q USING (request_id)
        WHERE q.issued_at >= ?
        ORDER BY re.request_id, re.ordinal
        """,
        (started_at.isoformat(),),
    ).fetchall()
    result: dict[str, tuple[str, str]] = {}
    for row in rows:
        request_id = str(row["request_id"])
        if request_id in result:
            continue
        if str(row["title"]) != "Polymarket Gamma market metadata":
            continue
        try:
            payload = json.loads(str(row["content"]))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, Mapping):
            continue
        category = str(payload.get("category") or UNKNOWN_CATEGORY).strip()
        event_id = str(payload.get("event_id") or "").strip()
        result[request_id] = (category or UNKNOWN_CATEGORY, event_id)
    return result


def load_cohort_attempts(
    journal: ForecastJournal,
    manifest: CohortManifest,
) -> tuple[CohortAttempt, ...]:
    if manifest.policy_id != DEFAULT_POLICY.policy_id:
        raise ValueError(
            f"unsupported cohort policy {manifest.policy_id!r}; "
            f"expected {DEFAULT_POLICY.policy_id!r}"
        )

    request_rows = journal.connection.execute(
        """
        SELECT q.*, r.outcome_yes
        FROM requests AS q
        LEFT JOIN resolutions AS r USING (condition_id)
        WHERE q.issued_at >= ?
        ORDER BY q.issued_at, q.request_id
        """,
        (manifest.started_at.isoformat(),),
    ).fetchall()
    metadata = _request_market_metadata(journal, started_at=manifest.started_at)

    forecast_rows = journal.connection.execute(
        """
        SELECT f.*
        FROM forecasts AS f
        JOIN requests AS q USING (request_id)
        WHERE q.issued_at >= ?
        """,
        (manifest.started_at.isoformat(),),
    ).fetchall()
    forecasts = {
        (str(row["request_id"]), str(row["provider"]), str(row["model"])): row
        for row in forecast_rows
    }

    failure_rows = journal.connection.execute(
        """
        SELECT ff.*
        FROM forecast_failures AS ff
        JOIN requests AS q USING (request_id)
        WHERE q.issued_at >= ?
        """,
        (manifest.started_at.isoformat(),),
    ).fetchall()
    failures = {
        (str(row["request_id"]), str(row["provider"]), str(row["model"])): row
        for row in failure_rows
    }

    attempts: list[CohortAttempt] = []
    for request in request_rows:
        request_id = str(request["request_id"])
        issued_at = _parse_datetime(str(request["issued_at"]))
        resolves_at = _optional_datetime(request["resolves_at"])
        category, event_id = metadata.get(
            request_id,
            (UNKNOWN_CATEGORY, ""),
        )
        baseline_text = str(request["baseline_probability"] or "").strip()
        baseline = Decimal(baseline_text) if baseline_text else None
        outcome = (
            None
            if request["outcome_yes"] is None
            else bool(request["outcome_yes"])
        )
        for forecaster in manifest.forecasters:
            key = (request_id, forecaster.provider, forecaster.model)
            forecast = forecasts.get(key)
            failure = failures.get(key)
            integrity_error: str | None = None
            if forecast is not None and failure is not None:
                integrity_error = "request has both forecast and provider failure"
            probability_text = (
                str(forecast["probability_yes"] or "").strip()
                if forecast is not None
                else ""
            )
            attempts.append(
                CohortAttempt(
                    request_id=request_id,
                    condition_id=str(request["condition_id"]),
                    event_id=event_id,
                    category=category,
                    horizon=horizon_bucket(issued_at, resolves_at),
                    issued_at=issued_at,
                    forecaster_key=forecaster.key,
                    outcome_yes=outcome,
                    baseline_probability=baseline,
                    forecast_probability=(
                        Decimal(probability_text) if probability_text else None
                    ),
                    abstain=(
                        bool(forecast["abstain"]) if forecast is not None else False
                    ),
                    failure_error=(str(failure["error"]) if failure is not None else None),
                    integrity_error=integrity_error,
                )
            )
    return tuple(attempts)


def _first_attempt_per_condition(
    attempts: Sequence[CohortAttempt],
) -> tuple[tuple[CohortAttempt, ...], int]:
    selected: dict[tuple[str, str], CohortAttempt] = {}
    repeat_count = 0
    for attempt in sorted(
        attempts,
        key=lambda item: (
            item.issued_at,
            item.request_id,
            item.condition_id,
            item.forecaster_key,
        ),
    ):
        key = (attempt.forecaster_key, attempt.condition_id)
        if key in selected:
            repeat_count += 1
            continue
        selected[key] = attempt
    ordered = tuple(
        sorted(
            selected.values(),
            key=lambda item: (
                item.forecaster_key,
                item.issued_at,
                item.condition_id,
            ),
        )
    )
    return ordered, repeat_count


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def _cluster_bootstrap_interval(
    values: Sequence[tuple[str, Decimal]],
    *,
    seed: str,
    iterations: int,
    confidence_level: Decimal,
) -> SkillInterval | None:
    if len(values) < 2:
        return None
    clusters: dict[str, list[Decimal]] = defaultdict(list)
    for cluster_id, value in values:
        clusters[cluster_id].append(value)
    cluster_keys = sorted(clusters)
    if len(cluster_keys) < 2:
        return None

    means: list[Decimal] = []
    cluster_count = len(cluster_keys)
    for iteration in range(iterations):
        sample_values: list[Decimal] = []
        for draw in range(cluster_count):
            digest = hashlib.sha256(
                f"{seed}\x1f{iteration}\x1f{draw}".encode()
            ).digest()
            index = int.from_bytes(digest[:8], "big") % cluster_count
            sample_values.extend(clusters[cluster_keys[index]])
        means.append(sum(sample_values, ZERO) / Decimal(len(sample_values)))
    means.sort()

    tail = (ONE - confidence_level) / Decimal(2)
    lower_index = int(tail * Decimal(iterations - 1))
    upper_index = int((ONE - tail) * Decimal(iterations - 1))
    return SkillInterval(means[lower_index], means[upper_index])


def _slice_summary(label: str, attempts: Sequence[CohortAttempt]) -> SliceSummary:
    resolved = [item for item in attempts if item.resolved]
    scored = [item for item in resolved if item.scored]
    abstentions = sum(1 for item in resolved if item.abstain and item.integrity_error is None)
    failures = sum(
        1
        for item in resolved
        if item.failure_error is not None and item.integrity_error is None
    )
    incomplete = sum(
        1
        for item in resolved
        if not item.scored
        and not item.abstain
        and item.failure_error is None
        and item.integrity_error is None
    )
    skills = [
        brier_score(item.baseline_probability, item.outcome_yes)
        - brier_score(item.forecast_probability, item.outcome_yes)
        for item in scored
        if item.baseline_probability is not None
        and item.forecast_probability is not None
        and item.outcome_yes is not None
    ]
    coverage = (
        Decimal(len(scored)) / Decimal(len(resolved)) if resolved else ZERO
    )
    return SliceSummary(
        label=label,
        resolved_conditions=len(resolved),
        scored_count=len(scored),
        abstention_count=abstentions,
        provider_failure_count=failures,
        incomplete_count=incomplete,
        coverage=coverage,
        mean_brier_skill_vs_market=_mean(skills),
    )


def _summaries_by(
    attempts: Sequence[CohortAttempt],
    *,
    field: str,
) -> tuple[SliceSummary, ...]:
    groups: dict[str, list[CohortAttempt]] = defaultdict(list)
    for item in attempts:
        groups[str(getattr(item, field))].append(item)
    return tuple(
        _slice_summary(label, groups[label])
        for label in sorted(groups)
    )


def _gate(name: str, passed: bool, observed: object, required: object) -> GateResult:
    return GateResult(
        name=name,
        state="PASS" if passed else "WAIT",
        observed=str(observed),
        required=str(required),
    )


def _decision_gate(
    name: str,
    *,
    ready: bool,
    passed: bool,
    observed: object,
    required: object,
) -> GateResult:
    state = "WAIT" if not ready else ("PASS" if passed else "FAIL")
    return GateResult(name, state, str(observed), str(required))


def qualify_forecaster(
    forecaster_key: str,
    attempts: Sequence[CohortAttempt],
    *,
    policy: QualificationPolicy = DEFAULT_POLICY,
    repeat_attempts_excluded: int = 0,
) -> ForecasterQualification:
    selected = [item for item in attempts if item.forecaster_key == forecaster_key]
    resolved = [item for item in selected if item.resolved]
    scored = [item for item in resolved if item.scored]
    integrity_errors = tuple(
        f"{item.request_id}: {item.integrity_error}"
        for item in selected
        if item.integrity_error is not None
    )
    abstentions = sum(1 for item in resolved if item.abstain and item.integrity_error is None)
    failures = sum(
        1
        for item in resolved
        if item.failure_error is not None and item.integrity_error is None
    )
    incomplete = sum(
        1
        for item in resolved
        if not item.scored
        and not item.abstain
        and item.failure_error is None
        and item.integrity_error is None
    )
    coverage = (
        Decimal(len(scored)) / Decimal(len(resolved)) if resolved else ZERO
    )

    brier_values = [
        brier_score(item.forecast_probability, item.outcome_yes)
        for item in scored
        if item.forecast_probability is not None and item.outcome_yes is not None
    ]
    market_brier_values = [
        brier_score(item.baseline_probability, item.outcome_yes)
        for item in scored
        if item.baseline_probability is not None and item.outcome_yes is not None
    ]
    brier_skills = [
        market - forecast
        for market, forecast in zip(market_brier_values, brier_values)
    ]
    log_values = [
        log_loss(item.forecast_probability, item.outcome_yes)
        for item in scored
        if item.forecast_probability is not None and item.outcome_yes is not None
    ]
    market_log_values = [
        log_loss(item.baseline_probability, item.outcome_yes)
        for item in scored
        if item.baseline_probability is not None and item.outcome_yes is not None
    ]
    log_skills = [
        market - forecast
        for market, forecast in zip(market_log_values, log_values)
    ]
    cluster_ids = [item.event_cluster for item in scored]
    brier_interval = _cluster_bootstrap_interval(
        list(zip(cluster_ids, brier_skills)),
        seed=f"{policy.policy_id}:{forecaster_key}:brier",
        iterations=policy.bootstrap_iterations,
        confidence_level=policy.confidence_level,
    )
    log_interval = _cluster_bootstrap_interval(
        list(zip(cluster_ids, log_skills)),
        seed=f"{policy.policy_id}:{forecaster_key}:log-loss",
        iterations=policy.bootstrap_iterations,
        confidence_level=policy.confidence_level,
    )

    calibration_samples = [
        (item.forecast_probability, item.outcome_yes)
        for item in scored
        if item.forecast_probability is not None and item.outcome_yes is not None
    ]
    ece = (
        expected_calibration_error(reliability_bins(calibration_samples))
        if calibration_samples
        else None
    )

    category_slices = _summaries_by(selected, field="category")
    horizon_slices = _summaries_by(selected, field="horizon")
    eligible_categories = [
        item
        for item in category_slices
        if item.label != UNKNOWN_CATEGORY and item.scored_count >= policy.min_slice_scored
    ]
    eligible_horizons = [
        item
        for item in horizon_slices
        if item.label not in {"Unknown", "Invalid"}
        and item.scored_count >= policy.min_slice_scored
    ]
    resolved_clusters = {item.event_cluster for item in resolved}

    evidence_gates = (
        _gate(
            "resolved_conditions",
            len(resolved) >= policy.min_resolved_conditions,
            len(resolved),
            f">={policy.min_resolved_conditions}",
        ),
        _gate(
            "resolved_event_clusters",
            len(resolved_clusters) >= policy.min_resolved_event_clusters,
            len(resolved_clusters),
            f">={policy.min_resolved_event_clusters}",
        ),
        _gate(
            "scored_forecasts",
            len(scored) >= policy.min_scored,
            len(scored),
            f">={policy.min_scored}",
        ),
        _gate(
            "category_diversity",
            len(eligible_categories) >= policy.min_category_slices,
            len(eligible_categories),
            f">={policy.min_category_slices} slices with >= {policy.min_slice_scored} scored",
        ),
        _gate(
            "horizon_diversity",
            len(eligible_horizons) >= policy.min_horizon_slices,
            len(eligible_horizons),
            f">={policy.min_horizon_slices} slices with >= {policy.min_slice_scored} scored",
        ),
    )
    decision_ready = all(item.state == "PASS" for item in evidence_gates)

    mean_brier_skill = _mean(brier_skills)
    slice_floor = -policy.max_slice_skill_deficit
    eligible_slice_skills = [
        item.mean_brier_skill_vs_market
        for item in (*eligible_categories, *eligible_horizons)
        if item.mean_brier_skill_vs_market is not None
    ]
    minimum_slice_skill = min(eligible_slice_skills) if eligible_slice_skills else None

    performance_gates = (
        _decision_gate(
            "coverage",
            ready=decision_ready,
            passed=coverage >= policy.min_coverage,
            observed=coverage,
            required=f">={policy.min_coverage}",
        ),
        _decision_gate(
            "mean_brier_skill_vs_market",
            ready=decision_ready,
            passed=mean_brier_skill is not None and mean_brier_skill > ZERO,
            observed=mean_brier_skill,
            required=">0",
        ),
        _decision_gate(
            "brier_skill_confidence_lower_bound",
            ready=decision_ready,
            passed=brier_interval is not None and brier_interval.lower > ZERO,
            observed=(brier_interval.lower if brier_interval else None),
            required=f">0 at {policy.confidence_level} event-cluster bootstrap confidence",
        ),
        _decision_gate(
            "expected_calibration_error",
            ready=decision_ready,
            passed=ece is not None and ece <= policy.max_ece,
            observed=ece,
            required=f"<={policy.max_ece}",
        ),
        _decision_gate(
            "slice_regression_floor",
            ready=decision_ready,
            passed=(
                minimum_slice_skill is not None
                and minimum_slice_skill >= slice_floor
            ),
            observed=minimum_slice_skill,
            required=f">={slice_floor}",
        ),
    )
    gates = (*evidence_gates, *performance_gates)

    if integrity_errors:
        status = "INVALID"
    elif not decision_ready:
        status = "COLLECTING"
    elif any(item.state == "FAIL" for item in performance_gates):
        status = "NOT_QUALIFIED"
    else:
        status = "ELIGIBLE_FOR_PAPER_PROPOSAL"

    return ForecasterQualification(
        forecaster_key=forecaster_key,
        status=status,
        total_conditions=len(selected),
        resolved_conditions=len(resolved),
        resolved_event_clusters=len(resolved_clusters),
        unresolved_conditions=len(selected) - len(resolved),
        repeat_attempts_excluded=repeat_attempts_excluded,
        scored_count=len(scored),
        abstention_count=abstentions,
        provider_failure_count=failures,
        incomplete_count=incomplete,
        coverage=coverage,
        mean_brier=_mean(brier_values),
        mean_market_brier=_mean(market_brier_values),
        mean_brier_skill_vs_market=mean_brier_skill,
        brier_skill_interval=brier_interval,
        mean_log_loss=_mean(log_values),
        mean_market_log_loss=_mean(market_log_values),
        mean_log_loss_skill_vs_market=_mean(log_skills),
        log_loss_skill_interval=log_interval,
        expected_calibration_error=ece,
        category_slices=category_slices,
        horizon_slices=horizon_slices,
        gates=tuple(gates),
        integrity_errors=integrity_errors,
    )


def qualify_cohort(
    journal: ForecastJournal,
    manifest: CohortManifest,
    *,
    policy: QualificationPolicy = DEFAULT_POLICY,
) -> CohortQualificationReport:
    if manifest.policy_id != policy.policy_id:
        raise ValueError(
            f"cohort policy {manifest.policy_id!r} does not match evaluator "
            f"policy {policy.policy_id!r}"
        )
    attempts = load_cohort_attempts(journal, manifest)
    selected, repeat_count = _first_attempt_per_condition(attempts)
    request_ids = {item.request_id for item in attempts}
    condition_ids = {item.condition_id for item in attempts}
    qualifications = tuple(
        qualify_forecaster(
            forecaster.key,
            selected,
            policy=policy,
            repeat_attempts_excluded=sum(
                1
                for item in attempts
                if item.forecaster_key == forecaster.key
            )
            - sum(
                1
                for item in selected
                if item.forecaster_key == forecaster.key
            ),
        )
        for forecaster in manifest.forecasters
    )
    if repeat_count < sum(item.repeat_attempts_excluded for item in qualifications):
        raise AssertionError("repeat-attempt accounting mismatch")
    return CohortQualificationReport(
        cohort_id=manifest.cohort_id,
        policy_id=policy.policy_id,
        manifest_sha256=manifest.sha256,
        started_at=manifest.started_at,
        request_count=len(request_ids),
        unique_condition_count=len(condition_ids),
        forecasters=qualifications,
    )
