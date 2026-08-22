#!/usr/bin/env python3
"""Collect a bounded batch of live, research-only probabilistic forecasts."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

AGENT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = AGENT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from adapters.polymarket.gamma import GammaAdapter  # noqa: E402
from config import settings  # noqa: E402
from evaluation.cohort_protocol import QualificationManifest  # noqa: E402
from forecasting.collection import (  # noqa: E402
    ClobSnapshotClient,
    EvidenceManifest,
    LiveForecastCollector,
    load_provider_specs,
    parse_iso_datetime,
)
from forecasting.evidence_templates import TemplatedEvidenceManifest  # noqa: E402
from forecasting.forecast import utc_now  # noqa: E402
from forecasting.journal import ForecastJournal  # noqa: E402


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


class CohortGammaAdapter:
    """Filter discovery to unseen, finite-horizon conditions in a fixed cohort."""

    def __init__(
        self,
        inner: GammaAdapter,
        *,
        excluded_condition_ids: set[str],
        max_horizon_days: int,
    ):
        self.inner = inner
        self.base_url = inner.base_url
        self.excluded_condition_ids = frozenset(excluded_condition_ids)
        self.max_horizon_days = max_horizon_days

    async def fetch_active_markets(self, *, limit: int):
        markets = await self.inner.fetch_active_markets(limit=limit)
        observed_at = utc_now()
        horizon_limit = observed_at + timedelta(days=self.max_horizon_days)
        eligible = []
        for market in markets:
            if market.condition_id in self.excluded_condition_ids:
                continue
            try:
                resolves_at = parse_iso_datetime(market.end_date)
            except ValueError:
                continue
            if resolves_at is None or resolves_at <= observed_at:
                continue
            if resolves_at > horizon_limit:
                continue
            eligible.append(market)
        return eligible


def validate_cohort(
    manifest: QualificationManifest,
    *,
    provider_specs: tuple[Any, ...],
    providers_path: Path,
    evidence_path: Path | None,
    db_path: Path,
    allow_market_metadata_only: bool,
) -> None:
    if evidence_path is None:
        raise ValueError("qualification cohort requires a preregistered evidence manifest")
    if allow_market_metadata_only:
        raise ValueError("qualification cohort forbids --allow-market-metadata-only")
    configured = tuple(
        sorted((spec.provider_name, spec.model_name) for spec in provider_specs)
    )
    registered = tuple(
        sorted(
            (item.provider, item.model)
            for item in manifest.cohort.forecasters
        )
    )
    if configured != registered:
        raise ValueError("provider configuration does not match cohort preregistration")
    manifest.validate_files(providers=providers_path, evidence=evidence_path)
    if utc_now() < manifest.cohort.started_at:
        raise ValueError("cohort collection cannot begin before preregistered start time")
    if db_path.resolve() == Path(settings.forecast_database_path).resolve():
        raise ValueError(
            "qualification cohort requires a dedicated --db path, not the default journal"
        )


def cohort_seen_conditions(
    journal: ForecastJournal,
    manifest: QualificationManifest,
) -> set[str]:
    prestart = journal.connection.execute(
        "SELECT COUNT(*) AS n FROM requests WHERE issued_at < ?",
        (manifest.cohort.started_at.isoformat(),),
    ).fetchone()
    if int(prestart["n"]) > 0:
        raise ValueError("qualification journal contains requests from before cohort start")
    rows = journal.connection.execute(
        """
        SELECT DISTINCT condition_id
        FROM requests
        WHERE issued_at >= ?
        """,
        (manifest.cohort.started_at.isoformat(),),
    ).fetchall()
    condition_ids = {str(row["condition_id"]) for row in rows}
    if len(condition_ids) > manifest.decision_condition_count:
        raise ValueError("qualification journal exceeds preregistered condition count")
    return condition_ids


async def run(args: argparse.Namespace) -> int:
    provider_specs = load_provider_specs(args.providers)
    providers = [spec.build() for spec in provider_specs]
    cohort = (
        QualificationManifest.from_path(args.cohort)
        if args.cohort is not None
        else None
    )
    if cohort is not None:
        validate_cohort(
            cohort,
            provider_specs=provider_specs,
            providers_path=args.providers,
            evidence_path=args.evidence,
            db_path=args.db,
            allow_market_metadata_only=args.allow_market_metadata_only,
        )

    evidence_manifest = TemplatedEvidenceManifest(
        EvidenceManifest.from_path(args.evidence)
        if args.evidence is not None
        else EvidenceManifest.empty()
    )
    journal = ForecastJournal(str(args.db))
    try:
        sample_count = args.sample_count
        discovery_limit = args.discovery_limit
        gamma: Any = GammaAdapter(args.gamma_url)
        if cohort is not None:
            seen = cohort_seen_conditions(journal, cohort)
            remaining = cohort.decision_condition_count - len(seen)
            if remaining == 0:
                print(
                    json.dumps(
                        {
                            "status": "COHORT_TARGET_FULL",
                            "cohort_id": cohort.cohort.cohort_id,
                            "condition_count": len(seen),
                            "decision_condition_count": cohort.decision_condition_count,
                            "qualification_manifest_sha256": cohort.sha256,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0
            sample_count = min(sample_count, remaining)
            discovery_limit = max(
                discovery_limit,
                min(500, cohort.decision_condition_count * 2),
            )
            gamma = CohortGammaAdapter(
                gamma,
                excluded_condition_ids=seen,
                max_horizon_days=cohort.max_resolution_horizon_days,
            )

        collector = LiveForecastCollector(
            providers,
            journal,
            gamma=gamma,
            clob=ClobSnapshotClient(args.clob_url),
        )
        summary = await collector.collect_once(
            evidence_manifest,
            sample_count=sample_count,
            discovery_limit=discovery_limit,
            max_book_age_ms=args.max_book_age_ms,
            allow_market_metadata_only=args.allow_market_metadata_only,
        )
    finally:
        journal.close()

    payload: Any = summary
    if cohort is not None:
        payload = {
            "cohort": {
                "cohort_id": cohort.cohort.cohort_id,
                "policy_id": cohort.cohort.policy_id,
                "started_at": cohort.cohort.started_at,
                "qualification_manifest_sha256": cohort.sha256,
                "decision_condition_count": cohort.decision_condition_count,
                "max_resolution_horizon_days": cohort.max_resolution_horizon_days,
            },
            "summary": summary,
        }
    print(json.dumps(jsonable(payload), indent=2, sort_keys=True))
    if not summary.collected:
        return 2
    if summary.forecast_count == 0:
        return 3
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze live market/evidence snapshots and run bounded research forecasts."
    )
    parser.add_argument("--providers", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--cohort", type=Path)
    parser.add_argument("--db", type=Path, default=Path(settings.forecast_database_path))
    parser.add_argument("--sample-count", type=int, default=3)
    parser.add_argument("--discovery-limit", type=int, default=settings.market_discovery_limit)
    parser.add_argument("--max-book-age-ms", type=int, default=settings.market_max_book_age_ms)
    parser.add_argument("--gamma-url", default=settings.polymarket_gamma_url)
    parser.add_argument("--clob-url", default=settings.polymarket_clob_url)
    parser.add_argument(
        "--allow-market-metadata-only",
        action="store_true",
        help="Permit question/market metadata without independent external evidence.",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
