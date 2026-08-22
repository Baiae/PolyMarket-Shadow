"""Immutable qualification protocol for a fixed out-of-sample decision cohort."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from forecasting.journal import ForecastJournal
from forecasting.provider import SYSTEM_PROMPT

from .cohort import (
    CohortManifest,
    CohortQualificationReport,
    ForecasterQualification,
    GateResult,
    QualificationPolicy,
    qualify_cohort,
)

FORECAST_PROTOCOL_ID = "PS-FP-1"
REQUEST_TEMPLATE_VERSION = "1"
DECISION_CONDITION_COUNT = 120
MAX_RESOLUTION_HORIZON_DAYS = 90

FIXED_POLICY = QualificationPolicy(
    policy_id="PS-FQ-1",
    min_resolved_conditions=DECISION_CONDITION_COUNT,
    min_resolved_event_clusters=60,
    min_scored=96,
    min_coverage=Decimal("0.80"),
    confidence_level=Decimal("0.95"),
    bootstrap_iterations=2000,
    max_ece=Decimal("0.10"),
    min_category_slices=3,
    min_horizon_slices=2,
    min_slice_scored=10,
    max_slice_skill_deficit=Decimal("0.02"),
)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()


def canonical_json_sha256(path: Path) -> str:
    """Hash JSON semantically so whitespace/key-order edits do not change identity."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def policy_mapping(policy: QualificationPolicy = FIXED_POLICY) -> dict[str, Any]:
    raw = asdict(policy)
    return {
        key: str(value) if isinstance(value, Decimal) else value
        for key, value in raw.items()
    }


def policy_sha256(policy: QualificationPolicy = FIXED_POLICY) -> str:
    return hashlib.sha256(_canonical_json(policy_mapping(policy))).hexdigest()


def forecast_protocol_sha256() -> str:
    payload = {
        "forecast_protocol_id": FORECAST_PROTOCOL_ID,
        "request_template_version": REQUEST_TEMPLATE_VERSION,
        "system_prompt": SYSTEM_PROMPT,
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _sha256(value: str, *, field: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{field} must be a SHA-256 hex digest")
    return normalized


@dataclass(frozen=True, slots=True)
class QualificationManifest:
    cohort: CohortManifest
    provider_config_sha256: str
    evidence_manifest_sha256: str
    policy_sha256: str
    forecast_protocol_sha256: str
    decision_condition_count: int = DECISION_CONDITION_COUNT
    max_resolution_horizon_days: int = MAX_RESOLUTION_HORIZON_DAYS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_config_sha256",
            _sha256(self.provider_config_sha256, field="provider_config_sha256"),
        )
        object.__setattr__(
            self,
            "evidence_manifest_sha256",
            _sha256(self.evidence_manifest_sha256, field="evidence_manifest_sha256"),
        )
        object.__setattr__(
            self,
            "policy_sha256",
            _sha256(self.policy_sha256, field="policy_sha256"),
        )
        object.__setattr__(
            self,
            "forecast_protocol_sha256",
            _sha256(self.forecast_protocol_sha256, field="forecast_protocol_sha256"),
        )
        if self.decision_condition_count != DECISION_CONDITION_COUNT:
            raise ValueError("unsupported decision_condition_count")
        if self.max_resolution_horizon_days != MAX_RESOLUTION_HORIZON_DAYS:
            raise ValueError("unsupported max_resolution_horizon_days")
        if self.cohort.policy_id != FIXED_POLICY.policy_id:
            raise ValueError("unsupported qualification policy ID")

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> QualificationManifest:
        return cls(
            cohort=CohortManifest.from_mapping(payload),
            provider_config_sha256=str(payload.get("provider_config_sha256") or ""),
            evidence_manifest_sha256=str(payload.get("evidence_manifest_sha256") or ""),
            policy_sha256=str(payload.get("policy_sha256") or ""),
            forecast_protocol_sha256=str(
                payload.get("forecast_protocol_sha256") or ""
            ),
            decision_condition_count=int(
                payload.get("decision_condition_count", DECISION_CONDITION_COUNT)
            ),
            max_resolution_horizon_days=int(
                payload.get(
                    "max_resolution_horizon_days",
                    MAX_RESOLUTION_HORIZON_DAYS,
                )
            ),
        )

    @classmethod
    def from_path(cls, path: Path) -> QualificationManifest:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("qualification manifest must be a JSON object")
        return cls.from_mapping(payload)

    def as_mapping(self) -> dict[str, Any]:
        return {
            **self.cohort.as_mapping(),
            "provider_config_sha256": self.provider_config_sha256,
            "evidence_manifest_sha256": self.evidence_manifest_sha256,
            "policy_sha256": self.policy_sha256,
            "forecast_protocol_sha256": self.forecast_protocol_sha256,
            "decision_condition_count": self.decision_condition_count,
            "max_resolution_horizon_days": self.max_resolution_horizon_days,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical_json(self.as_mapping())).hexdigest()

    def validate_files(self, *, providers: Path, evidence: Path) -> None:
        if canonical_json_sha256(providers) != self.provider_config_sha256:
            raise ValueError("provider configuration changed after cohort preregistration")
        if canonical_json_sha256(evidence) != self.evidence_manifest_sha256:
            raise ValueError("evidence manifest changed after cohort preregistration")
        if policy_sha256() != self.policy_sha256:
            raise ValueError("qualification policy changed after cohort preregistration")
        if forecast_protocol_sha256() != self.forecast_protocol_sha256:
            raise ValueError("forecast protocol changed after cohort preregistration")


def _terminalize_waiting_gates(
    qualification: ForecasterQualification,
) -> ForecasterQualification:
    gates = tuple(
        replace(gate, state="FAIL") if gate.state == "WAIT" else gate
        for gate in qualification.gates
    )
    return replace(
        qualification,
        status="NOT_QUALIFIED",
        gates=gates,
    )


def _invalidate(
    qualification: ForecasterQualification,
    error: str,
) -> ForecasterQualification:
    return replace(
        qualification,
        status="INVALID",
        integrity_errors=(*qualification.integrity_errors, error),
    )


def qualify_fixed_cohort(
    journal: ForecastJournal,
    manifest: QualificationManifest,
) -> CohortQualificationReport:
    """Evaluate exactly one fixed 120-condition cohort; continuous reports never add looks."""
    report = qualify_cohort(journal, manifest.cohort, policy=FIXED_POLICY)
    if report.unique_condition_count > manifest.decision_condition_count:
        return replace(
            report,
            forecasters=tuple(
                _invalidate(
                    item,
                    "cohort contains more unique conditions than the preregistered decision sample",
                )
                for item in report.forecasters
            ),
        )

    target_filled = report.unique_condition_count == manifest.decision_condition_count
    finalized: list[ForecasterQualification] = []
    for qualification in report.forecasters:
        if qualification.status == "INVALID":
            finalized.append(qualification)
            continue
        all_target_conditions_resolved = (
            target_filled
            and qualification.total_conditions == manifest.decision_condition_count
            and qualification.resolved_conditions == manifest.decision_condition_count
        )
        if all_target_conditions_resolved and qualification.status == "COLLECTING":
            finalized.append(_terminalize_waiting_gates(qualification))
        else:
            finalized.append(qualification)
    return replace(report, forecasters=tuple(finalized))
