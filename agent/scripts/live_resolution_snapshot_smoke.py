#!/usr/bin/env python3
"""Read-only live smoke for authoritative CLOB resolution state."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import aiohttp

AGENT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = AGENT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config import settings  # noqa: E402
from forecasting.forecast import utc_now  # noqa: E402
from forecasting.resolution import (  # noqa: E402
    ClobResolutionClient,
    observe_resolution,
)


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


async def closed_binary_conditions(limit: int = 100) -> list[str]:
    timeout = aiohttp.ClientTimeout(total=20)
    params = {"closed": "true", "limit": str(limit)}
    async with (
        aiohttp.ClientSession(timeout=timeout) as session,
        session.get(f"{settings.polymarket_gamma_url.rstrip('/')}/markets", params=params) as response,
    ):
        response.raise_for_status()
        payload: Any = await response.json()
    markets = payload if isinstance(payload, list) else payload.get("markets", [])
    condition_ids: list[str] = []
    for market in markets:
        if not isinstance(market, dict) or market.get("closed") is not True:
            continue
        outcomes = as_list(market.get("outcomes"))
        token_ids = as_list(market.get("clobTokenIds"))
        if len(outcomes) != 2 or len(token_ids) != 2:
            continue
        normalized = {str(outcome).strip().upper() for outcome in outcomes}
        if normalized != {"YES", "NO"}:
            continue
        condition_id = str(market.get("conditionId") or "").strip()
        if condition_id:
            condition_ids.append(condition_id)
    return condition_ids


async def run_smoke(output: Path, *, market_count: int) -> dict[str, Any]:
    if market_count < 1:
        raise ValueError("market_count must be positive")
    condition_ids = await closed_binary_conditions(100)
    if not condition_ids:
        raise RuntimeError("Gamma returned no closed binary markets")

    client = ClobResolutionClient(settings.polymarket_clob_url)
    resolved: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for condition_id in condition_ids[:40]:
        if len(resolved) >= market_count:
            break
        try:
            payload = await client.fetch_market(condition_id)
            observation = observe_resolution(
                payload,
                expected_condition_id=condition_id,
                observed_at=utc_now(),
                source=f"{client.base_url}/markets/{{condition_id}}",
            )
        except Exception as exc:
            rejected.append(
                {
                    "condition_id": condition_id,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        if observation is None:
            rejected.append(
                {"condition_id": condition_id, "reason": "no authoritative winner yet"}
            )
            continue
        resolved.append(
            {
                "condition_id": observation.condition_id,
                "winning_token_id": observation.winning_token_id,
                "winning_outcome": observation.winning_outcome,
                "resolution_id": observation.resolution_id,
                "observed_at": observation.observed_at.isoformat(),
                "source": observation.source,
            }
        )

    if len(resolved) < market_count:
        raise RuntimeError(
            f"only {len(resolved)} authoritative resolutions found; required {market_count}"
        )

    evidence = {
        "status": "PASS",
        "mode": "READ_ONLY_RESOLUTION_STATE",
        "provider_invocations": 0,
        "paper_orders_created": 0,
        "live_orders_created": 0,
        "gamma_closed_binary_candidates": len(condition_ids),
        "resolved_samples": resolved,
        "rejected_samples": rejected[:10],
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
                    "mode": "READ_ONLY_RESOLUTION_STATE",
                    "provider_invocations": 0,
                    "paper_orders_created": 0,
                    "live_orders_created": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        raise
    print(
        "LIVE_RESOLUTION_SNAPSHOT_SMOKE_PASS "
        f"resolutions={len(evidence['resolved_samples'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
