#!/usr/bin/env python3
"""Read-only live smoke for authoritative CLOB resolution state."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping
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

END_CURSOR = "LTE="


async def fetch_simplified_page(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    cursor: str | None,
) -> Mapping[str, Any]:
    params = {"next_cursor": cursor} if cursor else None
    async with session.get(
        f"{base_url.rstrip('/')}/simplified-markets",
        params=params,
    ) as response:
        response.raise_for_status()
        payload: Any = await response.json()
    if not isinstance(payload, Mapping):
        raise TypeError("CLOB simplified-markets response must be an object")
    if not isinstance(payload.get("data"), list):
        raise TypeError("CLOB simplified-markets response missing data array")
    return payload


async def run_smoke(
    output: Path,
    *,
    market_count: int,
    max_pages: int,
) -> dict[str, Any]:
    if market_count < 1:
        raise ValueError("market_count must be positive")
    if max_pages < 1:
        raise ValueError("max_pages must be positive")

    base_url = settings.polymarket_clob_url.rstrip("/")
    client = ClobResolutionClient(base_url)
    resolved: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    pages_scanned = 0
    markets_scanned = 0
    candidate_winners = 0
    cursor: str | None = None
    timeout = aiohttp.ClientTimeout(total=60)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for _ in range(max_pages):
            page = await fetch_simplified_page(
                session,
                base_url=base_url,
                cursor=cursor,
            )
            pages_scanned += 1
            data = page["data"]
            for item in data:
                markets_scanned += 1
                if not isinstance(item, Mapping):
                    continue
                condition_id = str(item.get("condition_id") or "").strip()
                if not condition_id:
                    continue
                try:
                    simplified_observation = observe_resolution(
                        item,
                        expected_condition_id=condition_id,
                        observed_at=utc_now(),
                        source=f"{base_url}/simplified-markets",
                    )
                except (TypeError, ValueError) as exc:
                    if len(rejected) < 20:
                        rejected.append(
                            {
                                "condition_id": condition_id,
                                "stage": "simplified-market",
                                "reason": f"{type(exc).__name__}: {exc}",
                            }
                        )
                    continue
                if simplified_observation is None:
                    continue
                candidate_winners += 1

                try:
                    payload = await client.fetch_market(condition_id)
                    observation = observe_resolution(
                        payload,
                        expected_condition_id=condition_id,
                        observed_at=utc_now(),
                        source=f"{base_url}/markets/{{condition_id}}",
                    )
                except (
                    aiohttp.ClientError,
                    asyncio.TimeoutError,
                    TypeError,
                    ValueError,
                ) as exc:
                    if len(rejected) < 20:
                        rejected.append(
                            {
                                "condition_id": condition_id,
                                "stage": "market-detail",
                                "reason": f"{type(exc).__name__}: {exc}",
                            }
                        )
                    continue
                if observation is None:
                    if len(rejected) < 20:
                        rejected.append(
                            {
                                "condition_id": condition_id,
                                "stage": "market-detail",
                                "reason": "detail endpoint did not expose authoritative winner",
                            }
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
                if len(resolved) >= market_count:
                    break

            if len(resolved) >= market_count:
                break
            next_cursor = str(page.get("next_cursor") or "").strip()
            if not next_cursor or next_cursor == END_CURSOR or next_cursor == cursor:
                break
            cursor = next_cursor

    status = "PASS" if len(resolved) >= market_count else "FAIL"
    evidence = {
        "status": status,
        "mode": "READ_ONLY_RESOLUTION_STATE",
        "provider_invocations": 0,
        "paper_orders_created": 0,
        "live_orders_created": 0,
        "pages_scanned": pages_scanned,
        "markets_scanned": markets_scanned,
        "simplified_authoritative_winner_candidates": candidate_winners,
        "resolved_samples": resolved,
        "rejected_samples": rejected,
        "terminal_cursor": cursor,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")

    if status != "PASS":
        raise RuntimeError(
            "insufficient authoritative CLOB resolutions: "
            f"found={len(resolved)} required={market_count} "
            f"pages={pages_scanned} markets={markets_scanned} "
            f"candidates={candidate_winners}"
        )
    return evidence


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--market-count", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=30)
    args = parser.parse_args()
    try:
        evidence = await run_smoke(
            args.output,
            market_count=args.market_count,
            max_pages=args.max_pages,
        )
    except Exception as exc:
        if not args.output.exists():
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
        f"resolutions={len(evidence['resolved_samples'])} "
        f"pages={evidence['pages_scanned']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
