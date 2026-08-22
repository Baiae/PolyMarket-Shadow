#!/usr/bin/env python3
"""Create an immutable-start forecast qualification cohort manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = AGENT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from evaluation.cohort import CohortManifest, ForecasterRef  # noqa: E402
from evaluation.cohort_protocol import (  # noqa: E402
    FIXED_POLICY,
    QualificationManifest,
    canonical_json_sha256,
    forecast_protocol_sha256,
    policy_sha256,
)
from forecasting.collection import (  # noqa: E402
    EvidenceManifest,
    load_provider_specs,
)
from forecasting.forecast import utc_now  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-register a fixed out-of-sample forecasting qualification cohort."
    )
    parser.add_argument("--cohort-id", required=True)
    parser.add_argument("--providers", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(
            f"refusing to overwrite existing cohort manifest: {args.output}"
        )

    specs = load_provider_specs(args.providers)
    EvidenceManifest.from_path(args.evidence)
    cohort = CohortManifest(
        cohort_id=args.cohort_id,
        policy_id=FIXED_POLICY.policy_id,
        started_at=utc_now(),
        forecasters=tuple(
            ForecasterRef(spec.provider_name, spec.model_name) for spec in specs
        ),
        dedicated_journal=True,
    )
    manifest = QualificationManifest(
        cohort=cohort,
        provider_config_sha256=canonical_json_sha256(args.providers),
        evidence_manifest_sha256=canonical_json_sha256(args.evidence),
        policy_sha256=policy_sha256(),
        forecast_protocol_sha256=forecast_protocol_sha256(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest.as_mapping(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "cohort_id": cohort.cohort_id,
                "policy_id": cohort.policy_id,
                "started_at": cohort.started_at.isoformat(),
                "qualification_manifest_sha256": manifest.sha256,
                "provider_config_sha256": manifest.provider_config_sha256,
                "evidence_manifest_sha256": manifest.evidence_manifest_sha256,
                "policy_sha256": manifest.policy_sha256,
                "forecast_protocol_sha256": manifest.forecast_protocol_sha256,
                "decision_condition_count": manifest.decision_condition_count,
                "max_resolution_horizon_days": manifest.max_resolution_horizon_days,
                "forecasters": [item.key for item in cohort.forecasters],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
