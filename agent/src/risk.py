import logging
from dataclasses import dataclass, field
from datetime import datetime
from config import settings

log = logging.getLogger(__name__)


@dataclass
class PositionSize:
    market_id: str
    side: str
    kelly_fraction: float
    recommended_usd: float
    portfolio_pct: float


class RiskManager:
    def __init__(self, initial_bankroll: float = 1000.0):
        self._initial_bankroll = initial_bankroll
        self._current_bankroll = initial_bankroll
        self._peak_bankroll = initial_bankroll
        self._killed: bool = False
        self._kill_reason: str = ""
        self._kill_timestamp: datetime | None = None
        self._order_timestamps: list[datetime] = []
        self.pnl_history: list[dict] = []

    @property
    def is_killed(self) -> bool:
        return self._killed

    @property
    def kill_reason(self) -> str:
        return self._kill_reason

    def check_drawdown(self) -> bool:
        if self._killed:
            return True
        drawdown = (self._peak_bankroll - self._current_bankroll) / self._peak_bankroll
        if drawdown >= settings.max_drawdown_pct:
            self._killed = True
            self._kill_reason = (
                f"Drawdown {drawdown:.1%} exceeded {settings.max_drawdown_pct:.0%}. "
                f"Peak: ${self._peak_bankroll:,.2f} | Now: ${self._current_bankroll:,.2f}"
            )
            self._kill_timestamp = datetime.utcnow()
            log.critical(f"🛑 KILL SWITCH: {self._kill_reason}")
        return self._killed

    def resume(self) -> None:
        log.warning("Kill switch manually reset by operator.")
        self._killed = False
        self._kill_reason = ""
        self._kill_timestamp = None

    def size_position(self, market_id: str, side: str,
                      edge: float, price: float) -> PositionSize | None:
        if self._killed or edge <= 0:
            return None
        odds = (1.0 - price) / price if price > 0 else 1.0
        full_kelly = edge / odds
        fractional_kelly = full_kelly * settings.kelly_fraction
        max_pct = min(fractional_kelly, 0.05)
        recommended_usd = self._current_bankroll * max_pct
        return PositionSize(
            market_id=market_id, side=side,
            kelly_fraction=fractional_kelly,
            recommended_usd=round(recommended_usd, 2),
            portfolio_pct=round(max_pct * 100, 2),
        )

    def update_bankroll(self, new_value: float, note: str = "") -> None:
        self._current_bankroll = new_value
        if new_value > self._peak_bankroll:
            self._peak_bankroll = new_value
        self.pnl_history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "bankroll": new_value, "note": note,
        })
        self.check_drawdown()

    @property
    def stats(self) -> dict:
        drawdown = (self._peak_bankroll - self._current_bankroll) / self._peak_bankroll
        return {
            "initial_bankroll": self._initial_bankroll,
            "current_bankroll": self._current_bankroll,
            "peak_bankroll": self._peak_bankroll,
            "drawdown_pct": round(drawdown * 100, 2),
            "total_return_pct": round(
                (self._current_bankroll - self._initial_bankroll)
                / self._initial_bankroll * 100, 2),
            "kill_switch_active": self._killed,
            "kill_reason": self._kill_reason,
        }

    def can_place_order(self) -> bool:
        now = datetime.utcnow()
        self._order_timestamps = [
            t for t in self._order_timestamps
            if (now - t).total_seconds() < 60
        ]
        if len(self._order_timestamps) >= 60:
            log.warning("Rate limit: 60 orders/min reached")
            return False
        self._order_timestamps.append(now)
        return True
