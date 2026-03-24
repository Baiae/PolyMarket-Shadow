"""
test_arbitrage.py — Unit tests for ArbitrageDetector.

Tests cover: signal detection, edge calculation, threshold boundary,
signal accumulation and history cap. No API calls required.
"""
import pytest
from dataclasses import dataclass
from strategy.arbitrage import ArbitrageDetector


# ── Minimal market stub ───────────────────────────────────────────────────────

@dataclass
class FakeMarket:
    """Minimal stand-in for MarketMeta — only fields ArbitrageDetector uses."""
    market_id: str
    question: str
    yes_price: float
    no_price: float


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def detector():
    return ArbitrageDetector()


def make_market(yes: float, no: float, mid: str = "mkt_1") -> FakeMarket:
    return FakeMarket(
        market_id=mid,
        question=f"Will {mid} resolve YES?",
        yes_price=yes,
        no_price=no,
    )

# ── Detection ─────────────────────────────────────────────────────────────────

class TestArbDetection:
    def test_detects_arb_below_threshold(self, detector):
        """YES + NO = 0.95 — clear arb opportunity."""
        markets = [make_market(yes=0.50, no=0.45)]
        signals = detector.scan(markets)
        assert len(signals) == 1

    def test_no_signal_at_threshold(self, detector):
        """YES + NO = 0.98 — exactly at threshold, no signal."""
        markets = [make_market(yes=0.50, no=0.48)]
        signals = detector.scan(markets)
        assert len(signals) == 0

    def test_no_signal_above_threshold(self, detector):
        """YES + NO = 1.00 — efficient market, no arb."""
        markets = [make_market(yes=0.50, no=0.50)]
        signals = detector.scan(markets)
        assert len(signals) == 0

    def test_no_signal_overpriced(self, detector):
        """YES + NO = 1.05 — overpriced (no arb to exploit here)."""
        markets = [make_market(yes=0.55, no=0.50)]
        signals = detector.scan(markets)
        assert len(signals) == 0

    def test_multiple_markets_only_flags_arb(self, detector):
        """Three markets: one arb, two efficient."""
        markets = [
            make_market(yes=0.48, no=0.45, mid="arb_mkt"),    # 0.93 — arb
            make_market(yes=0.50, no=0.50, mid="fair_mkt"),   # 1.00 — no arb
            make_market(yes=0.60, no=0.42, mid="ok_mkt"),     # 1.02 — no arb
        ]
        signals = detector.scan(markets)
        assert len(signals) == 1
        assert signals[0].market_id == "arb_mkt"


# ── Edge calculation ──────────────────────────────────────────────────────────

class TestEdgeCalculation:
    def test_edge_is_1_minus_combined(self, detector):
        markets = [make_market(yes=0.45, no=0.45)]   # combined = 0.90
        signals = detector.scan(markets)
        assert signals[0].edge_usd == pytest.approx(0.10, abs=0.001)

    def test_combined_price_stored_correctly(self, detector):
        markets = [make_market(yes=0.47, no=0.48)]   # combined = 0.95
        signals = detector.scan(markets)
        assert signals[0].combined == pytest.approx(0.95, abs=0.001)

    def test_signal_preserves_market_id_and_question(self, detector):
        markets = [make_market(yes=0.45, no=0.45, mid="test_market")]
        signals = detector.scan(markets)
        assert signals[0].market_id == "test_market"
        assert "test_market" in signals[0].question


# ── Signal history ────────────────────────────────────────────────────────────

class TestSignalHistory:
    def test_signals_accumulate_across_scans(self, detector):
        detector.scan([make_market(0.40, 0.40, "mkt_a")])
        detector.scan([make_market(0.40, 0.40, "mkt_b")])
        assert len(detector.signals) == 2

    def test_empty_scan_adds_nothing(self, detector):
        detector.scan([make_market(0.50, 0.50)])   # no arb
        assert len(detector.signals) == 0

    def test_history_capped_at_500(self, detector):
        """Flood detector with 600 markets — history should not exceed 500."""
        markets = [make_market(0.40, 0.40, f"mkt_{i}") for i in range(600)]
        detector.scan(markets)
        assert len(detector.signals) <= 500
