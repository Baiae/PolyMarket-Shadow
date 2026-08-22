"""Canonical Polymarket identity and trading-constraint model."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


class MarketIdentityError(ValueError):
    """Raised when a Gamma market cannot be mapped to a binary CLOB market."""


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


@dataclass(frozen=True, slots=True)
class MarketIdentity:
    gamma_market_id: str
    condition_id: str
    yes_token_id: str
    no_token_id: str
    question: str
    event_id: str = ""
    slug: str = ""
    category: str = ""
    end_date: str = ""
    fees_enabled: bool = False
    fee_rate: Decimal = Decimal(0)
    fee_exponent: Decimal = Decimal(1)
    maker_rebate_rate: Decimal = Decimal(0)
    minimum_tick_size: Decimal | None = None
    minimum_order_size: Decimal | None = None

    @property
    def token_ids(self) -> tuple[str, str]:
        return (self.yes_token_id, self.no_token_id)

    def token_for_side(self, side: str) -> str:
        normalized = side.strip().upper()
        if normalized == "YES":
            return self.yes_token_id
        if normalized == "NO":
            return self.no_token_id
        raise KeyError(f"unknown binary side: {side!r}")

    def side_for_token(self, token_id: str) -> str:
        if token_id == self.yes_token_id:
            return "YES"
        if token_id == self.no_token_id:
            return "NO"
        raise KeyError(
            f"token {token_id!r} does not belong to market {self.gamma_market_id}"
        )

    @classmethod
    def from_gamma(
        cls, market: Mapping[str, Any], *, event_id: str = ""
    ) -> MarketIdentity:
        gamma_id = str(market.get("id") or "").strip()
        condition_id = str(
            market.get("conditionId") or market.get("condition_id") or ""
        ).strip()
        question = str(market.get("question") or "").strip()
        if not gamma_id:
            raise MarketIdentityError("missing Gamma market id")
        if not condition_id:
            raise MarketIdentityError(f"market {gamma_id} missing condition id")

        yes_token = ""
        no_token = ""
        outcomes_obj = market.get("outcomes")
        if isinstance(outcomes_obj, Mapping):
            yes_obj = outcomes_obj.get("yes") or outcomes_obj.get("Yes") or {}
            no_obj = outcomes_obj.get("no") or outcomes_obj.get("No") or {}
            if isinstance(yes_obj, Mapping):
                yes_token = str(
                    yes_obj.get("tokenId") or yes_obj.get("token_id") or ""
                ).strip()
            if isinstance(no_obj, Mapping):
                no_token = str(
                    no_obj.get("tokenId") or no_obj.get("token_id") or ""
                ).strip()

        if not yes_token or not no_token:
            token_ids = _as_list(
                market.get("clobTokenIds")
                or market.get("clob_token_ids")
                or market.get("tokenIds")
                or market.get("token_ids")
            )
            outcome_names = _as_list(outcomes_obj)
            if len(token_ids) != 2:
                raise MarketIdentityError(
                    f"market {gamma_id} is not a complete binary CLOB market"
                )
            if len(outcome_names) == 2:
                mapping = {
                    str(name).strip().upper(): str(token).strip()
                    for name, token in zip(outcome_names, token_ids)
                }
                yes_token = yes_token or mapping.get("YES", "")
                no_token = no_token or mapping.get("NO", "")
            else:
                yes_token = yes_token or str(token_ids[0]).strip()
                no_token = no_token or str(token_ids[1]).strip()

        if not yes_token or not no_token or yes_token == no_token:
            raise MarketIdentityError(
                f"market {gamma_id} missing distinct YES/NO CLOB token IDs"
            )

        category = str(market.get("category") or "").strip()
        if not category:
            tags = market.get("tags")
            if (
                isinstance(tags, Sequence)
                and not isinstance(tags, (str, bytes))
                and tags
            ):
                first = tags[0]
                if isinstance(first, Mapping):
                    category = str(
                        first.get("label") or first.get("name") or ""
                    ).strip()
                else:
                    category = str(first).strip()

        fee_schedule = market.get("feeSchedule") or market.get("fee_schedule") or {}
        if not isinstance(fee_schedule, Mapping):
            fee_schedule = {}

        tick_raw = market.get("orderPriceMinTickSize")
        if tick_raw is None:
            tick_raw = market.get("minimum_tick_size")
        min_order_raw = market.get("orderMinSize")
        if min_order_raw is None:
            min_order_raw = market.get("minimum_order_size")

        return cls(
            gamma_market_id=gamma_id,
            condition_id=condition_id,
            yes_token_id=yes_token,
            no_token_id=no_token,
            question=question,
            event_id=str(
                event_id or market.get("eventId") or market.get("event_id") or ""
            ).strip(),
            slug=str(market.get("slug") or "").strip(),
            category=category,
            end_date=str(
                market.get("endDate") or market.get("end_date") or ""
            ).strip(),
            fees_enabled=bool(
                market.get("feesEnabled")
                if "feesEnabled" in market
                else market.get("fees_enabled", False)
            ),
            fee_rate=_decimal(fee_schedule.get("rate"), "0"),
            fee_exponent=_decimal(fee_schedule.get("exponent"), "1"),
            maker_rebate_rate=_decimal(
                fee_schedule.get("rebateRate")
                if "rebateRate" in fee_schedule
                else fee_schedule.get("rebate_rate"),
                "0",
            ),
            minimum_tick_size=(
                _decimal(tick_raw) if tick_raw not in (None, "") else None
            ),
            minimum_order_size=(
                _decimal(min_order_raw) if min_order_raw not in (None, "") else None
            ),
        )
