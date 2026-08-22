#!/usr/bin/env python3
"""Read-only live Gamma + CLOB batch-book smoke for forecast baselines."""

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
    baseline_from_snapshots,
)
from forecasting.forecast import utc_now  # noqa: E402


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


async def run_smoke(output: Path, *, market_count: int) -> dict[str, Any]:
    if market_count < 1:
        raise ValueError("market_count must be positive")
    gamma = GammaAdapter()
    clob = ClobSnapshotClient(settings.polymarket_clob_url)
    markets = await gamma.fetch_active_markets(limit=100)
    if not markets:
        raise RuntimeError("Gamma returned no trade-ready binary markets")

    candidates = markets[: min(len(markets), max(market_count * 4, market_count))]
    token_ids = [token for market in candidates for token in market.token_ids]
    snapshots = await clob.fetch_books(token_ids)
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for market in candidates:
        if len(valid) >= market_count:
            break
        try:
            baseline = baseline_from_snapshots(
                market,
                snapshots,
                observed_at=utc_now(),
                max_age_ms=120_000,
                source=f"{clob.base_url}/books",
            )
        except ValueError as exc:
            rejected.append(
                {
                    "condition_id": market.condition_id,
                    "reason": str(exc),
                }
            )
            continue
        yes = snapshots[market.yes_token_id]
        no = snapshots[market.no_token_id]
        valid.append(
            {
                "gamma_market_id": market.gamma_market_id,
                "condition_id": market.condition_id,
                "slug": market.slug,
                "baseline": jsonable(baseline),
                "yes_book": {
                    "token_id": market.yes_token_id,
                    "captured_at": yes.captured_at.isoformat(),
                    "best_bid": jsonable(yes.book.best_bid),
                    "best_ask": jsonable(yes.book.best_ask),
                    "hash": yes.book.hash,
                },
                "no_book": {
                    "token_id": market.no_token_id,
                    "captured_at": no.captured_at.isoformat(),
                    "best_bid": jsonable(no.book.best_bid),
                    "best_ask": jsonable(no.book.best_ask),
                    "hash": no.book.hash,
                },
            }
        )

    if not valid:
        raise RuntimeError("no candidate produced a fresh two-sided YES/NO baseline")

    evidence = {
        "status": "PASS",
        "mode": "READ_ONLY_FORECAST_BASELINE",
        "paper_orders_created": 0,
        "live_orders_created": 0,
        "providers_invoked": 0,
        "gamma_trade_ready_markets_discovered": len(markets),
        "candidate_markets": len(candidates),
        "valid_baselines": valid,
        "rejected_candidates": rejected,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return evidence


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--market-count", type=int, default=3)
    args = parser.parse_args()
    try:
        evidence = await run_smoke(args.output, market_count=args.market_count)
    except Exception as exc:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "status": "FAIL",
                    "mode": "READ_ONLY_FORECAST_BASELINE",
                    "paper_orders_created": 0,
                    "live_orders_created": 0,
                    "providers_invoked": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        raise

    print(
        "LIVE_FORECAST_SNAPSHOT_SMOKE_PASS "
        f"baselines={len(evidence['valid_baselines'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
