import json
from decimal import Decimal
from pathlib import Path

import pytest

from adapters.polymarket.models import (
    BookEvent,
    MarketResolvedEvent,
    PriceChangeEvent,
    normalize_market_event,
)
from adapters.polymarket.stream import PolymarketStream


FIXTURES = Path(__file__).parent / "fixtures" / "polymarket"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_normalizes_current_raw_book_event():
    event = normalize_market_event(load("book.json"))
    assert isinstance(event, BookEvent)
    assert event.token_id.startswith("107505")
    assert event.bids[0].price == Decimal("0.08")
    assert event.asks[0].price == Decimal("0.09")
    assert event.timestamp_ms == 1782753357257


def test_replays_live_book_pair_captured_2026_08_22():
    fixture = load("live_book_pair_2026-08-22.json")
    identity = fixture["gamma_market"]
    events = [normalize_market_event(raw) for raw in fixture["book_events"]]

    assert all(isinstance(event, BookEvent) for event in events)
    assert {event.condition_id for event in events} == {identity["condition_id"]}
    assert {event.token_id for event in events} == {
        identity["yes_token_id"],
        identity["no_token_id"],
    }
    assert all(event.timestamp_ms == 1787424054186 for event in events)
    assert all(event.bids and event.asks for event in events)


def test_normalizes_current_price_change_event():
    event = normalize_market_event(load("price_change.json"))
    assert isinstance(event, PriceChangeEvent)
    assert len(event.changes) == 1
    assert event.changes[0].side == "BUY"
    assert event.changes[0].best_ask == Decimal("0.09")


def test_normalizes_market_resolution():
    event = normalize_market_event(load("market_resolved.json"))
    assert isinstance(event, MarketResolvedEvent)
    assert event.gamma_market_id == "703257"
    assert event.winning_outcome == "YES"
    assert event.winning_token_id in event.token_ids


def test_unknown_stream_event_is_ignored():
    assert normalize_market_event({"event_type": "heartbeat"}) is None


def test_subscription_uses_clob_token_ids_and_custom_events():
    payload = PolymarketStream.subscription_payload(["yes", "no", "yes"])
    assert payload == {
        "assets_ids": ["yes", "no"],
        "type": "market",
        "custom_feature_enabled": True,
    }


@pytest.mark.asyncio
async def test_stream_message_replay_requires_no_network():
    seen = []
    stream = PolymarketStream(["token"], seen.append, url="wss://example.invalid")
    await stream.process_message(json.dumps(load("book.json")))
    assert len(seen) == 1
    assert isinstance(seen[0], BookEvent)
