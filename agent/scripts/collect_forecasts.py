#!/usr/bin/env python3
"""Collect a bounded batch of live, research-only probabilistic forecasts."""

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

from adapters.polymarket.gamma import GammaAdapter  # noqa: E402
from config import settings  # noqa: E402
from forecasting.collection import (  # noqa: E402
    ClobSnapshotClient,
    EvidenceManifest,
    LiveForecastCollector,
    load_provider_specs,
)
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


async def run(args: argparse.Namespace) -> int:
    provider_specs = load_provider_specs(args.providers)
    providers = [spec.build() for spec in provider_specs]
    manifest = (
        EvidenceManifest.from_path(args.evidence)
        if args.evidence is not None
        else EvidenceManifest.empty()
    )
    journal = ForecastJournal(str(args.db))
    try:
        collector = LiveForecastCollector(
            providers,
            journal,
            gamma=GammaAdapter(args.gamma_url),
            clob=ClobSnapshotClient(args.clob_url),
        )
        summary = await collector.collect_once(
            manifest,
            sample_count=args.sample_count,
            discovery_limit=args.discovery_limit,
            max_book_age_ms=args.max_book_age_ms,
            allow_market_metadata_only=args.allow_market_metadata_only,
        )
    finally:
        journal.close()

    print(json.dumps(jsonable(summary), indent=2, sort_keys=True))
    if not summary.collected:
        return 2
    if summary.forecast_count == 0:
        return 3
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze live market/evidence snapshots and run bounded research forecasts."
    )
    parser.add_argument("--providers", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--db", type=Path, default=Path(settings.forecast_database_path))
    parser.add_argument("--sample-count", type=int, default=3)
    parser.add_argument("--discovery-limit", type=int, default=settings.market_discovery_limit)
    parser.add_argument("--max-book-age-ms", type=int, default=settings.market_max_book_age_ms)
    parser.add_argument("--gamma-url", default=settings.polymarket_gamma_url)
    parser.add_argument("--clob-url", default=settings.polymarket_clob_url)
    parser.add_argument(
        "--allow-market-metadata-only",
        action="store_true",
        help="Permit question/market metadata without independent external evidence.",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
