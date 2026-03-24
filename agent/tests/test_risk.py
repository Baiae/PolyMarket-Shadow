"""
test_risk.py — Unit tests for RiskManager.

Tests cover: Kelly sizing, drawdown kill switch, rate limiting,
bankroll tracking, and manual resume. No API calls required.
"""
import pytest
from risk import RiskManager


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def risk():
    """Fresh RiskManager with $1,000 starting bankroll."""
    return RiskManager(initial_bankroll=1000.0)


# ── Kill switch ───────────────────────────────────────────────────────────────

class TestKillSwitch:
    def test_not_killed_on_init(self, risk):
        assert risk.is_killed is False

    def test_triggers_at_30_pct_drawdown(self, risk):
        risk.update_bankroll(700.0)   # 30% drawdown exactly
        assert risk.is_killed is True

    def test_triggers_above_30_pct(self, risk):
        risk.update_bankroll(600.0)   # 40% drawdown
        assert risk.is_killed is True

    def test_does_not_trigger_below_30_pct(self, risk):
        risk.update_bankroll(720.0)   # 28% drawdown — safe
        assert risk.is_killed is False

    def test_kill_reason_contains_drawdown_info(self, risk):
        risk.update_bankroll(700.0)
        assert "30%" in risk.kill_reason or "Drawdown" in risk.kill_reason

    def test_resume_clears_kill(self, risk):
        risk.update_bankroll(700.0)
        assert risk.is_killed is True
        risk.resume()
        assert risk.is_killed is False
        assert risk.kill_reason == ""

    def test_sizing_blocked_when_killed(self, risk):
        risk.update_bankroll(700.0)
        result = risk.size_position("mkt_1", "YES", edge=0.1, price=0.5)
        assert result is None

# ── Kelly sizing ──────────────────────────────────────────────────────────────

class TestKellySizing:
    def test_returns_position_on_positive_edge(self, risk):
        result = risk.size_position("mkt_1", "YES", edge=0.1, price=0.5)
        assert result is not None
        assert result.recommended_usd > 0

    def test_returns_none_on_zero_edge(self, risk):
        result = risk.size_position("mkt_1", "YES", edge=0.0, price=0.5)
        assert result is None

    def test_returns_none_on_negative_edge(self, risk):
        result = risk.size_position("mkt_1", "YES", edge=-0.05, price=0.5)
        assert result is None

    def test_quarter_kelly_caps_at_5_pct_bankroll(self, risk):
        # Even with a huge edge, max bet is 5% of bankroll = $50
        result = risk.size_position("mkt_1", "YES", edge=0.9, price=0.1)
        assert result is not None
        assert result.recommended_usd <= 50.0

    def test_market_id_and_side_preserved(self, risk):
        result = risk.size_position("mkt_xyz", "NO", edge=0.1, price=0.4)
        assert result is not None
        assert result.market_id == "mkt_xyz"
        assert result.side == "NO"

    def test_sizing_scales_with_bankroll(self, risk):
        risk.update_bankroll(2000.0)
        result = risk.size_position("mkt_1", "YES", edge=0.1, price=0.5)
        assert result is not None
        assert result.recommended_usd <= 100.0   # 5% of $2,000


# ── Bankroll tracking ─────────────────────────────────────────────────────────

class TestBankrollTracking:
    def test_peak_updates_on_gain(self, risk):
        risk.update_bankroll(1200.0)
        assert risk.stats["peak_bankroll"] == 1200.0

    def test_peak_does_not_drop(self, risk):
        risk.update_bankroll(1200.0)
        risk.update_bankroll(900.0)
        assert risk.stats["peak_bankroll"] == 1200.0

    def test_pnl_history_records_entries(self, risk):
        risk.update_bankroll(1100.0, note="good trade")
        assert len(risk.pnl_history) == 1
        assert risk.pnl_history[0]["bankroll"] == 1100.0

    def test_stats_returns_correct_return_pct(self, risk):
        risk.update_bankroll(1100.0)
        assert risk.stats["total_return_pct"] == 10.0

    def test_drawdown_pct_correct(self, risk):
        risk.update_bankroll(1200.0)   # new peak
        risk.update_bankroll(960.0)    # 20% drawdown from peak
        assert risk.stats["drawdown_pct"] == pytest.approx(20.0, abs=0.1)


# ── Rate limiter ──────────────────────────────────────────────────────────────

class TestRateLimiter:
    def test_allows_first_order(self, risk):
        assert risk.can_place_order() is True

    def test_allows_up_to_60_orders(self, risk):
        for _ in range(60):
            assert risk.can_place_order() is True

    def test_blocks_61st_order(self, risk):
        for _ in range(60):
            risk.can_place_order()
        assert risk.can_place_order() is False
