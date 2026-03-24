import csv
import logging
import os
from datetime import datetime
from pathlib import Path

from config import settings

log = logging.getLogger(__name__)

CSV_HEADER = [
    "timestamp", "market_id", "question", "source",
    "consensus", "yes_count", "no_count", "no_trade_count", "confidence",
    "side", "size_usd", "price", "status",
    "model_deepseek", "model_gpt4omini", "model_claude",
    "model_qwen", "model_grok", "model_llama",
    "resolved", "resolution", "pnl_usd",
]


class FeedbackLogger:
    def __init__(self):
        Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
        Path(os.path.dirname(settings.csv_path)).mkdir(parents=True, exist_ok=True)
        if not os.path.exists(settings.csv_path):
            with open(settings.csv_path, "w", newline="") as f:
                csv.writer(f).writerow(CSV_HEADER)
            log.info(f"CSV created at {settings.csv_path}")

    def log_swarm_signal(self, signal, order=None) -> None:
        verdicts = [p.verdict.value for p in signal.predictions]
        row = {
            "timestamp": signal.timestamp.isoformat(),
            "market_id": signal.market_id,
            "question": signal.question,
            "source": "SWARM",
            "consensus": signal.consensus.value,
            "yes_count": signal.yes_count,
            "no_count": signal.no_count,
            "no_trade_count": signal.no_trade_count,
            "confidence": signal.confidence,
            "side": order.side if order else signal.consensus.value,
            "size_usd": order.size_usd if order else 0,
            "price": order.price if order else 0,
            "status": order.status.value if order else "NO_TRADE",
            "model_deepseek":  verdicts[0] if len(verdicts) > 0 else "",
            "model_gpt4omini": verdicts[1] if len(verdicts) > 1 else "",
            "model_claude":    verdicts[2] if len(verdicts) > 2 else "",
            "model_qwen":      verdicts[3] if len(verdicts) > 3 else "",
            "model_grok":      verdicts[4] if len(verdicts) > 4 else "",
            "model_llama":     verdicts[5] if len(verdicts) > 5 else "",
            "resolved": "", "resolution": "", "pnl_usd": "",
        }
        self._write(row)

    def log_arb_signal(self, signal, orders=None) -> None:
        row = {
            "timestamp": datetime.utcnow().isoformat(),
            "market_id": signal.market_id,
            "question": signal.question,
            "source": "ARB", "consensus": "ARB",
            "yes_count": 0, "no_count": 0, "no_trade_count": 0,
            "confidence": signal.edge_usd, "side": "BOTH",
            "size_usd": sum(o.size_usd for o in orders) if orders else 0,
            "price": signal.combined,
            "status": orders[0].status.value if orders else "PAPER",
            **{k: "" for k in ["model_deepseek", "model_gpt4omini", "model_claude",
                               "model_qwen", "model_grok", "model_llama",
                               "resolved", "resolution", "pnl_usd"]},
        }
        self._write(row)

    def _write(self, row: dict) -> None:
        try:
            with open(settings.csv_path, "a", newline="") as f:
                csv.DictWriter(f, fieldnames=CSV_HEADER).writerow(row)
        except Exception as exc:
            log.error(f"CSV write failed: {exc}")
