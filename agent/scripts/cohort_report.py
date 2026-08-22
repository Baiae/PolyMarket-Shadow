#!/usr/bin/env python3
"""Monitor a pre-registered out-of-sample forecast qualification cohort."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

AGENT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = AGENT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from evaluation.cohort import CohortManifest, qualify_cohort  # noqa: E402
from forecasting.journal import ForecastJournal  # noqa: E402


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def render_once(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    manifest = CohortManifest.from_path(args.cohort)
    journal = ForecastJournal(str(args.db))
    try:
        report = qualify_cohort(journal, manifest)
    finally:
        journal.close()
    payload = jsonable(report)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(payload, indent=2, sort_keys=True))

    statuses = {item.status for item in report.forecasters}
    if "INVALID" in statuses:
        return 2, payload
    if args.require_eligible and statuses != {"ELIGIBLE_FOR_PAPER_PROPOSAL"}:
        return 3, payload
    return 0, payload


async def run(args: argparse.Namespace) -> int:
    if not args.watch:
        code, _ = render_once(args)
        return code
    if args.interval_seconds < 60:
        raise ValueError("watch interval must be at least 60 seconds")
    while True:
        code, _ = render_once(args)
        if code == 2:
            print("cohort report contains integrity errors", file=sys.stderr)
        await asyncio.sleep(args.interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report fixed-policy cohort skill, calibration, coverage and slices."
    )
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument(
        "--db",
        type=Path,
        required=True,
        help="Dedicated SQLite forecasting journal for this cohort.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument(
        "--require-eligible",
        action="store_true",
        help="Exit 3 unless every configured forecaster is eligible for a paper proposal.",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
