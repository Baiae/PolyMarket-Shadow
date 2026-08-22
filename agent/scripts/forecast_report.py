"""Print proper-score summaries from the append-only forecasting journal."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from config import settings
from evaluation.report import summarize_resolved
from forecasting.journal import ForecastJournal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=settings.forecast_database_path)
    args = parser.parse_args()

    journal = ForecastJournal(args.db)
    try:
        summaries = summarize_resolved(journal.resolved_forecasts())
    finally:
        journal.close()

    payload = []
    for summary in summaries:
        item = asdict(summary)
        for key, value in tuple(item.items()):
            if key.startswith("mean_"):
                item[key] = str(value)
        item["beats_market"] = summary.beats_market
        item["mean_brier_skill_vs_market"] = str(
            summary.mean_brier_skill_vs_market
        )
        payload.append(item)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
