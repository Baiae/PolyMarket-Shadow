"""Normalized events for Polymarket's public market WebSocket.

The raw API uses ``event_type`` and CLOB ``asset_id`` values.  This module is
the only place where those wire names are interpreted; the rest of Poly-Shadow
consumes explicit token IDs and condition IDs.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from domain.orderbook import PriceLevel, as_decimal


@dataclass(frozen=True, slots=True)
class BookEvent:
    condition_id: str
    token_id: str
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]
    timestamp_ms: int | None
    book_hash: str | None = None


@dataclass(frozen=True, slots=True)
class PriceChange:
    token_id: str
    price: Decimal
    size: Decimal
    side: str
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None
    book_hash: str | None = None


@dataclass(frozen=True, slots=True)
class PriceChangeEvent:
    condition_id: str
    changes: tuple[PriceChange, ...]
    timestamp_ms: int | None


@dataclass(frozen=True, slots=True)
class LastTradeEvent:
    condition_id: str
    token_id: str
    price: Decimal
    size: Decimal | None
    side: str
    fee_rate_bps: Decimal | None
    timestamp_ms: int | None
    transaction_hash: str | None = None


@dataclass(frozen=True, slots=True)
class BestBidAskEvent:
    condition_id: str
    token_id: str
    best_bid: Decimal | None
    best_ask: Decimal | None
    spread: Decimal | None
    timestamp_ms: int | None


@dataclass(frozen=True, slots=True)
class MarketResolvedEvent:
    gamma_market_id: str
    condition_id: str
    token_ids: tuple[str, ...]
    winning_token_id: str
    winning_outcome: str
    timestamp_ms: int | None


NormalizedMarketEvent = (
    BookEvent
    | PriceChangeEvent
    | LastTradeEvent
    | BestBidAskEvent
    | MarketResolvedEvent
)


def _first(raw: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in raw:
            return raw[name]
    return default


def _timestamp(raw: Mapping[str, Any]) -> int | None:
    value = _first(raw, "timestamp", "timestamp_ms")
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return as_decimal(value)


def _payload(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    value = raw.get("payload")
    return value if isinstance(value, Mapping) else raw


def _event_type(raw: Mapping[str, Any]) -> str:
    return str(_first(raw, "event_type", "type", default="")).strip().lower()


def normalize_market_event(raw: Mapping[str, Any]) -> NormalizedMarketEvent | None:
    """Normalize current raw-API or SDK-shaped market-stream events."""

    event_type = _event_type(raw)
    payload = _payload(raw)
    condition_id = str(_first(payload, "market", "condition_id", "conditionId", default=""))

    if event_type == "book":
        token_id = str(_first(payload, "asset_id", "token_id", "tokenId", default=""))
        if not condition_id or not token_id:
            return None
        bids = tuple(PriceLevel.from_mapping(level) for level in payload.get("bids", []))
        asks = tuple(PriceLevel.from_mapping(level) for level in payload.get("asks", []))
        return BookEvent(
            condition_id=condition_id,
            token_id=token_id,
            bids=bids,
            asks=asks,
            timestamp_ms=_timestamp(payload),
            book_hash=_first(payload, "hash", default=None),
        )

    if event_type == "price_change":
        raw_changes = _first(payload, "price_changes", "priceChanges", default=[])
        changes: list[PriceChange] = []
        for change in raw_changes or []:
            if not isinstance(change, Mapping):
                continue
            token_id = str(_first(change, "asset_id", "token_id", "tokenId", default=""))
            if not token_id:
                continue
            side = str(change.get("side") or "").upper()
            if side not in {"BUY", "SELL"}:
                continue
            changes.append(PriceChange(
                token_id=token_id,
                price=as_decimal(change.get("price")),
                size=as_decimal(change.get("size")),
                side=side,
                best_bid=_optional_decimal(_first(change, "best_bid", "bestBid")),
                best_ask=_optional_decimal(_first(change, "best_ask", "bestAsk")),
                book_hash=_first(change, "hash", default=None),
            ))
        if not condition_id or not changes:
            return None
        return PriceChangeEvent(
            condition_id=condition_id,
            changes=tuple(changes),
            timestamp_ms=_timestamp(payload),
        )

    if event_type == "last_trade_price":
        token_id = str(_first(payload, "asset_id", "token_id", "tokenId", default=""))
        if not condition_id or not token_id:
            return None
        return LastTradeEvent(
            condition_id=condition_id,
            token_id=token_id,
            price=as_decimal(payload.get("price")),
            size=_optional_decimal(payload.get("size")),
            side=str(payload.get("side") or "").upper(),
            fee_rate_bps=_optional_decimal(_first(payload, "fee_rate_bps", "feeRateBps")),
            timestamp_ms=_timestamp(payload),
            transaction_hash=_first(payload, "transaction_hash", "transactionHash", default=None),
        )

    if event_type == "best_bid_ask":
        token_id = str(_first(payload, "asset_id", "token_id", "tokenId", default=""))
        if not condition_id or not token_id:
            return None
        return BestBidAskEvent(
            condition_id=condition_id,
            token_id=token_id,
            best_bid=_optional_decimal(_first(payload, "best_bid", "bestBid")),
            best_ask=_optional_decimal(_first(payload, "best_ask", "bestAsk")),
            spread=_optional_decimal(payload.get("spread")),
            timestamp_ms=_timestamp(payload),
        )

    if event_type == "market_resolved":
        token_ids = _first(payload, "assets_ids", "token_ids", "tokenIds", default=[])
        if not isinstance(token_ids, (list, tuple)):
            token_ids = []
        winning = str(_first(
            payload,
            "winning_asset_id",
            "winning_token_id",
            "winningTokenId",
            default="",
        ))
        gamma_id = str(payload.get("id") or "")
        if not condition_id or not gamma_id or not winning:
            return None
        return MarketResolvedEvent(
            gamma_market_id=gamma_id,
            condition_id=condition_id,
            token_ids=tuple(str(token) for token in token_ids),
            winning_token_id=winning,
            winning_outcome=str(_first(
                payload, "winning_outcome", "winningOutcome", default=""
            )).upper(),
            timestamp_ms=_timestamp(payload),
        )

    return None
