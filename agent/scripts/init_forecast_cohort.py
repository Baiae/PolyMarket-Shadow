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

from evaluation.cohort import (  # noqa: E402
    DEFAULT_POLICY,
    CohortManifest,
    ForecasterRef,
)
from forecasting.collection import load_provider_specs  # noqa: E402
from forecasting.forecast import utc_now  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-register a dedicated-journal forecasting qualification cohort."
    )
    parser.add_argument("--cohort-id", required=True)
    parser.add_argument("--providers", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(
            f"refusing to overwrite existing cohort manifest: {args.output}"
        )

    specs = load_provider_specs(args.providers)
    manifest = CohortManifest(
        cohort_id=args.cohort_id,
        policy_id=DEFAULT_POLICY.policy_id,
        started_at=utc_now(),
        forecasters=tuple(
            ForecasterRef(spec.provider_name, spec.model_name) for spec in specs
        ),
        dedicated_journal=True,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest.as_mapping(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "cohort_id": manifest.cohort_id,
                "policy_id": manifest.policy_id,
                "started_at": manifest.started_at.isoformat(),
                "manifest_sha256": manifest.sha256,
                "forecasters": [item.key for item in manifest.forecasters],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
