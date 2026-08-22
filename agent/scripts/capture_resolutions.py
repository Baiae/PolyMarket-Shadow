#!/usr/bin/env python3
"""Capture authoritative Polymarket outcomes into the forecast research journal."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = AGENT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config import settings  # noqa: E402
from forecasting.journal import ForecastJournal  # noqa: E402
from forecasting.resolution import (  # noqa: E402
    ClobResolutionClient,
    ResolutionCapture,
)


async def capture_once(args: argparse.Namespace) -> int:
    journal = ForecastJournal(str(args.db))
    try:
        capture = ResolutionCapture(
            journal,
            client=ClobResolutionClient(args.clob_url),
            concurrency=args.concurrency,
        )
        summary = await capture.capture_once(limit=args.limit)
    finally:
        journal.close()
    print(json.dumps(asdict(summary), indent=2, sort_keys=True))
    return 2 if summary.failures else 0


async def run(args: argparse.Namespace) -> int:
    if not args.watch:
        return await capture_once(args)
    if args.interval_seconds < 60:
        raise ValueError("watch interval must be at least 60 seconds")
    while True:
        code = await capture_once(args)
        if code != 0:
            print("resolution capture completed with isolated failures", file=sys.stderr)
        await asyncio.sleep(args.interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mature unresolved forecast records using public CLOB winner state."
    )
    parser.add_argument("--db", type=Path, default=Path(settings.forecast_database_path))
    parser.add_argument("--clob-url", default=settings.polymarket_clob_url)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
