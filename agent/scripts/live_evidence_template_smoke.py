#!/usr/bin/env python3
"""Read-only live smoke for deterministic market-specific GDELT evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp

AGENT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = AGENT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from domain.market import MarketIdentity  # noqa: E402
from forecasting.collection import EvidenceManifest  # noqa: E402
from forecasting.evidence_templates import TemplatedEvidenceManifest  # noqa: E402

TEMPLATE = (
    "https://api.gdeltproject.org/api/v2/doc/doc?"
    "query={gdelt_query}&mode=artlist&maxrecords=5&timespan=30d&format=json"
)


def synthetic_market(question: str, suffix: str) -> MarketIdentity:
    return MarketIdentity(
        gamma_market_id=f"smoke-gamma-{suffix}",
        condition_id=f"smoke-condition-{suffix}",
        yes_token_id=f"smoke-yes-{suffix}",
        no_token_id=f"smoke-no-{suffix}",
        question=question,
        slug=f"smoke-{suffix}",
    )


async def fetch_json(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
    async with session.get(
        url,
        headers={"User-Agent": "Poly-Shadow/0.5-evidence-smoke"},
    ) as response:
        response.raise_for_status()
        payload: Any = await response.json(content_type=None)
    if not isinstance(payload, dict):
        raise TypeError("GDELT evidence response must be a JSON object")
    articles = payload.get("articles")
    if not isinstance(articles, list):
        raise TypeError("GDELT Article List JSON must contain an articles array")
    return payload


async def run_smoke(output: Path) -> dict[str, Any]:
    raw = EvidenceManifest.from_mapping(
        {
            "markets": {
                "*": [
                    {
                        "source": TEMPLATE,
                        "title": "GDELT recent news search",
                    }
                ]
            }
        }
    )
    manifest = TemplatedEvidenceManifest(raw)
    markets = (
        synthetic_market(
            "Will bitcoin exceed 150,000 dollars before September 2026?",
            "bitcoin",
        ),
        synthetic_market(
            "Will Apple release a foldable iPhone before 2027?",
            "apple",
        ),
    )
    sources = [manifest.for_market(market)[0].source for market in markets]
    if len(set(sources)) != len(sources):
        raise RuntimeError("market-specific evidence templates rendered identical URLs")

    timeout = aiohttp.ClientTimeout(total=30)
    samples: list[dict[str, Any]] = []
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for market, source in zip(markets, sources):
            if "{" in source or "}" in source:
                raise RuntimeError("rendered evidence source contains unresolved template")
            parsed = urlparse(source)
            params = parse_qs(parsed.query)
            if parsed.netloc != "api.gdeltproject.org":
                raise RuntimeError("evidence source rendered unexpected host")
            if params.get("mode") != ["artlist"] or params.get("format") != ["json"]:
                raise RuntimeError("evidence source rendered wrong GDELT mode/format")
            payload = await fetch_json(session, source)
            samples.append(
                {
                    "condition_id": market.condition_id,
                    "question": market.question,
                    "source": source,
                    "article_count": len(payload["articles"]),
                }
            )

    evidence = {
        "status": "PASS",
        "mode": "READ_ONLY_DYNAMIC_EVIDENCE",
        "provider_invocations": 0,
        "paper_orders_created": 0,
        "live_orders_created": 0,
        "sample_count": len(samples),
        "samples": samples,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return evidence


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = await run_smoke(args.output)
    print(
        "LIVE_EVIDENCE_TEMPLATE_SMOKE_PASS "
        f"samples={evidence['sample_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
