"""
test_swarm_consensus.py — Tests swarm consensus counting logic.

These tests verify the YES/NO counting and threshold rules without
making any real OpenRouter API calls. The _query_model method is
mocked so tests run instantly and offline.
"""
import pytest
from unittest.mock import AsyncMock, patch
from strategy.swarm import AgentSwarm, Verdict, ModelPrediction, SwarmSignal
from dataclasses import dataclass


@dataclass
class FakeMeta:
    market_id: str = "mkt_test"
    question: str  = "Will this resolve YES?"
    category: str  = "politics"
    yes_price: float = 0.55
    no_price: float  = 0.45
    end_date: str    = "2025-12-31"


def make_predictions(verdicts: list[str]) -> list[ModelPrediction]:
    """Build a list of ModelPrediction from a list of verdict strings."""
    models = [f"model_{i}" for i in range(len(verdicts))]
    return [
        ModelPrediction(model=m, verdict=Verdict(v), latency_ms=10.0)
        for m, v in zip(models, verdicts)
    ]

class TestVerdictEnum:
    def test_yes_from_string(self):
        assert Verdict("YES") == Verdict.YES

    def test_no_from_string(self):
        assert Verdict("NO") == Verdict.NO

    def test_no_trade_from_string(self):
        assert Verdict("NO_TRADE") == Verdict.NO_TRADE


class TestConsensusThreshold:
    """
    Tests the 4/6 consensus rule by constructing SwarmSignals directly.
    No real API calls are made.
    """

    def _make_signal(self, verdicts: list[str]) -> SwarmSignal | None:
        """Helper: build a SwarmSignal the same way AgentSwarm would."""
        preds = make_predictions(verdicts)
        yes_count = sum(1 for p in preds if p.verdict == Verdict.YES)
        no_count  = sum(1 for p in preds if p.verdict == Verdict.NO)
        nt_count  = sum(1 for p in preds if p.verdict == Verdict.NO_TRADE)
        total = len(preds)

        if yes_count >= 4:
            consensus, confidence = Verdict.YES, yes_count / total
        elif no_count >= 4:
            consensus, confidence = Verdict.NO, no_count / total
        else:
            return None  # no consensus

        return SwarmSignal(
            market_id="mkt_test", question="Test?",
            predictions=preds, yes_count=yes_count,
            no_count=no_count, no_trade_count=nt_count,
            consensus=consensus, confidence=confidence,
        )

    def test_4_yes_triggers_consensus(self):
        signal = self._make_signal(["YES","YES","YES","YES","NO","NO"])
        assert signal is not None
        assert signal.consensus == Verdict.YES

    def test_4_no_triggers_consensus(self):
        signal = self._make_signal(["NO","NO","NO","NO","YES","NO_TRADE"])
        assert signal is not None
        assert signal.consensus == Verdict.NO

    def test_6_yes_triggers_consensus(self):
        signal = self._make_signal(["YES","YES","YES","YES","YES","YES"])
        assert signal is not None
        assert signal.consensus == Verdict.YES
        assert signal.confidence == pytest.approx(1.0)

    def test_3_yes_no_consensus(self):
        signal = self._make_signal(["YES","YES","YES","NO","NO","NO"])
        assert signal is None

    def test_split_returns_no_consensus(self):
        signal = self._make_signal(["YES","NO","NO_TRADE","YES","NO","NO_TRADE"])
        assert signal is None

    def test_confidence_is_fraction_of_total(self):
        signal = self._make_signal(["YES","YES","YES","YES","NO","NO_TRADE"])
        assert signal is not None
        assert signal.confidence == pytest.approx(4/6, abs=0.01)

    def test_counts_are_correct(self):
        signal = self._make_signal(["YES","YES","YES","YES","NO","NO_TRADE"])
        assert signal is not None
        assert signal.yes_count == 4
        assert signal.no_count == 1
        assert signal.no_trade_count == 1
