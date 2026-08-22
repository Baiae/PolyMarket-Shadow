"""Ledger-backed paper risk controls."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal

from accounting.ledger import Ledger
from config import settings


ZERO = Decimal(0)


class RiskManager:
    def __init__(
        self,
        ledger: Ledger,
        *,
        max_drawdown_pct: Decimal | str | None = None,
        max_position_pct: Decimal | str = "0.05",
    ):
        self.ledger = ledger
        self.max_drawdown_pct = Decimal(
            str(
                settings.max_drawdown_pct
                if max_drawdown_pct is None
                else max_drawdown_pct
            )
        )
        self.max_position_pct = Decimal(str(max_position_pct))
        self._peak_equity = ledger.initial_cash
        self._last_equity = ledger.initial_cash
        self._last_drawdown = ZERO
        self._killed = False
        self._kill_reason = ""
        self._kill_timestamp: datetime | None = None
        self._order_timestamps: list[datetime] = []

    @property
    def is_killed(self) -> bool:
        return self._killed

    @property
    def kill_reason(self) -> str:
        return self._kill_reason

    def kill(self, reason: str) -> None:
        self._killed = True
        self._kill_reason = reason or "manually triggered"
        self._kill_timestamp = datetime.now(timezone.utc)

    def resume(self) -> None:
        self._killed = False
        self._kill_reason = ""
        self._kill_timestamp = None

    def evaluate(self, mark_prices: Mapping[str, Decimal]) -> bool:
        equity = self.ledger.equity(mark_prices)
        self._last_equity = equity
        self._peak_equity = max(self._peak_equity, equity)
        if self._peak_equity > ZERO:
            self._last_drawdown = (
                self._peak_equity - equity
            ) / self._peak_equity
        else:
            self._last_drawdown = ZERO
        if self._last_drawdown >= self.max_drawdown_pct and not self._killed:
            self.kill(
                f"Drawdown {self._last_drawdown:.1%} exceeded "
                f"{self.max_drawdown_pct:.0%}; "
                f"peak={self._peak_equity}, equity={equity}"
            )
        return self._killed

    def can_allocate(
        self, cost: Decimal, mark_prices: Mapping[str, Decimal]
    ) -> bool:
        if cost <= ZERO or self.evaluate(mark_prices):
            return False
        if cost > self.ledger.available_cash:
            return False
        return cost <= self._last_equity * self.max_position_pct

    def can_place_order(self) -> bool:
        if self._killed:
            return False
        now = datetime.now(timezone.utc)
        self._order_timestamps = [
            timestamp
            for timestamp in self._order_timestamps
            if (now - timestamp).total_seconds() < 60
        ]
        if len(self._order_timestamps) >= 60:
            return False
        self._order_timestamps.append(now)
        return True

    @property
    def stats(self) -> dict:
        return {
            "initial_cash": str(self.ledger.initial_cash),
            "cash": str(self.ledger.cash),
            "available_cash": str(self.ledger.available_cash),
            "equity": str(self._last_equity),
            "peak_equity": str(self._peak_equity),
            "drawdown_pct": float(self._last_drawdown * 100),
            "realized_pnl": str(self.ledger.realized_pnl),
            "kill_switch_active": self._killed,
            "kill_reason": self._kill_reason,
        }
