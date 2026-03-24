import logging
from dataclasses import dataclass
from config import settings

log = logging.getLogger(__name__)


@dataclass
class ArbSignal:
    market_id: str
    question: str
    yes_price: float
    no_price: float
    combined: float
    edge_usd: float
    signal: str = "ARB"


class ArbitrageDetector:
    """
    Flags markets where YES + NO < arb_threshold (default 0.98).
    Buying both sides locks in (1.00 - combined) profit per share on resolution.
    """

    def __init__(self):
        self.signals: list[ArbSignal] = []

    def scan(self, markets: list) -> list[ArbSignal]:
        new_signals = []
        for m in markets:
            combined = m.yes_price + m.no_price
            if combined < settings.arb_threshold:
                edge = round((1.0 - combined), 4)
                signal = ArbSignal(
                    market_id=m.market_id, question=m.question,
                    yes_price=m.yes_price, no_price=m.no_price,
                    combined=round(combined, 4), edge_usd=edge,
                )
                new_signals.append(signal)
                log.warning(
                    f"⚡ ARB: {m.question[:60]} | "
                    f"YES={m.yes_price:.3f}+NO={m.no_price:.3f}={combined:.3f} "
                    f"(edge: ${edge*100:.1f}¢/share)"
                )
        self.signals.extend(new_signals)
        if len(self.signals) > 500:
            self.signals = self.signals[-500:]
        return new_signals
