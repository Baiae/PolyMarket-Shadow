#!/usr/bin/env python3
"""Read-only live Gamma + market-WebSocket smoke for the v0.2 adapter."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import websockets

AGENT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = AGENT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from adapters.polymarket.gamma import GammaAdapter  # noqa: E402
from adapters.polymarket.models import BookEvent, PriceChangeEvent  # noqa: E402
from adapters.polymarket.stream import PolymarketStream  # noqa: E402
from domain.orderbook import OrderBook  # noqa: E402


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def trim_raw_event(raw: Any) -> Any:
    """Keep public wire shape while bounding artifact size."""
    if isinstance(raw, list):
        return [trim_raw_event(item) for item in raw[:8]]
    if not isinstance(raw, dict):
        return raw
    result = dict(raw)
    for key in ("bids", "asks", "price_changes", "priceChanges"):
        value = result.get(key)
        if isinstance(value, list):
            result[key] = value[:5]
    payload = result.get("payload")
    if isinstance(payload, dict):
        result["payload"] = trim_raw_event(payload)
    return result


async def run_smoke(output: Path, *, seconds: float, market_count: int) -> dict[str, Any]:
    gamma = GammaAdapter()
    markets = await gamma.fetch_active_markets(limit=100)
    if not markets:
        raise RuntimeError("Gamma returned no trade-ready binary markets")

    selected = markets[: max(1, min(market_count, len(markets)))]
    token_to_market = {
        token: market
        for market in selected
        for token in market.token_ids
    }
    books = {token: OrderBook(token) for token in token_to_market}
    counts: Counter[str] = Counter()
    normalized_samples: list[Any] = []
    raw_samples: list[Any] = []

    async def on_event(event: Any) -> None:
        counts[type(event).__name__] += 1
        if len(normalized_samples) < 12:
            normalized_samples.append(jsonable(event))

        if isinstance(event, BookEvent):
            market = token_to_market.get(event.token_id)
            if market is None:
                raise RuntimeError(f"received book for unsubscribed token {event.token_id}")
            if event.condition_id != market.condition_id:
                raise RuntimeError(
                    "condition/token identity mismatch: "
                    f"{event.condition_id} != {market.condition_id}"
                )
            books[event.token_id].apply_snapshot(
                bids=[{"price": level.price, "size": level.size} for level in event.bids],
                asks=[{"price": level.price, "size": level.size} for level in event.asks],
                timestamp_ms=event.timestamp_ms,
                book_hash=event.book_hash,
            )
        elif isinstance(event, PriceChangeEvent):
            for change in event.changes:
                market = token_to_market.get(change.token_id)
                if market is None:
                    raise RuntimeError(
                        f"received price change for unsubscribed token {change.token_id}"
                    )
                if event.condition_id != market.condition_id:
                    raise RuntimeError("price-change condition/token identity mismatch")
                books[change.token_id].apply_change(
                    side=change.side,
                    price=change.price,
                    size=change.size,
                    timestamp_ms=event.timestamp_ms,
                    book_hash=change.book_hash,
                )

    stream = PolymarketStream(token_to_market.keys(), on_event)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds

    async with websockets.connect(stream.url, ping_interval=20, ping_timeout=10) as websocket:
        await websocket.send(json.dumps(stream.subscription_payload(token_to_market.keys())))
        while loop.time() < deadline:
            remaining = max(0.1, deadline - loop.time())
            try:
                raw_message = await asyncio.wait_for(
                    websocket.recv(), timeout=min(5.0, remaining)
                )
            except TimeoutError:
                continue
            try:
                decoded = json.loads(raw_message)
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                decoded = None
            if decoded is not None and len(raw_samples) < 12:
                raw_samples.append(trim_raw_event(decoded))
            await stream.process_message(raw_message)

            complete = [
                market
                for market in selected
                if books[market.yes_token_id].timestamp_ms is not None
                and books[market.no_token_id].timestamp_ms is not None
            ]
            if complete and counts["BookEvent"] >= 2:
                break

    complete_markets = [
        market
        for market in selected
        if books[market.yes_token_id].timestamp_ms is not None
        and books[market.no_token_id].timestamp_ms is not None
    ]
    if not complete_markets:
        raise RuntimeError("no selected market produced both YES and NO book snapshots")

    for market in complete_markets:
        for token in market.token_ids:
            book = books[token]
            if book.best_bid is not None and not (Decimal(0) <= book.best_bid <= Decimal(1)):
                raise RuntimeError("best bid outside prediction-market bounds")
            if book.best_ask is not None and not (Decimal(0) <= book.best_ask <= Decimal(1)):
                raise RuntimeError("best ask outside prediction-market bounds")

    evidence = {
        "status": "PASS",
        "mode": "READ_ONLY_MARKET_DATA",
        "paper_orders_created": 0,
        "live_orders_created": 0,
        "gamma_trade_ready_markets_discovered": len(markets),
        "selected_markets": [jsonable(market) for market in selected],
        "complete_market_ids": [market.gamma_market_id for market in complete_markets],
        "event_counts": dict(counts),
        "book_summaries": {
            token: {
                "condition_id": token_to_market[token].condition_id,
                "best_bid": jsonable(book.best_bid),
                "best_ask": jsonable(book.best_ask),
                "spread": jsonable(book.spread),
                "timestamp_ms": book.timestamp_ms,
                "bid_levels": len(book.bids),
                "ask_levels": len(book.asks),
            }
            for token, book in books.items()
            if book.timestamp_ms is not None
        },
        "normalized_samples": normalized_samples,
        "raw_samples": raw_samples,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return evidence


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=25.0)
    parser.add_argument("--market-count", type=int, default=3)
    args = parser.parse_args()

    try:
        evidence = await run_smoke(
            args.output, seconds=args.seconds, market_count=args.market_count
        )
    except Exception as exc:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "status": "FAIL",
                    "mode": "READ_ONLY_MARKET_DATA",
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
        "LIVE_ADAPTER_SMOKE_PASS "
        f"markets={len(evidence['complete_market_ids'])} "
        f"events={evidence['event_counts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
