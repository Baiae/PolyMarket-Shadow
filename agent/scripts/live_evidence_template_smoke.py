#!/usr/bin/env python3
"""Read-only live smoke for deterministic market-specific GDELT evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class FetchResult:
    payload: dict[str, Any] | None
    rate_limited: bool
    attempts: int
    retry_after: str | None = None


def synthetic_market(question: str, suffix: str) -> MarketIdentity:
    return MarketIdentity(
        gamma_market_id=f"smoke-gamma-{suffix}",
        condition_id=f"smoke-condition-{suffix}",
        yes_token_id=f"smoke-yes-{suffix}",
        no_token_id=f"smoke-no-{suffix}",
        question=question,
        slug=f"smoke-{suffix}",
    )


async def fetch_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    max_attempts: int = 3,
) -> FetchResult:
    """Retry bounded 429s; all other contract/HTTP failures remain fatal."""
    retry_after: str | None = None
    for attempt in range(1, max_attempts + 1):
        async with session.get(
            url,
            headers={"User-Agent": "Poly-Shadow/0.5-evidence-smoke"},
        ) as response:
            if response.status == 429:
                retry_after = response.headers.get("Retry-After")
                await response.read()
                if attempt < max_attempts:
                    await asyncio.sleep(2**attempt)
                    continue
                return FetchResult(
                    payload=None,
                    rate_limited=True,
                    attempts=attempt,
                    retry_after=retry_after,
                )
            response.raise_for_status()
            payload: Any = await response.json(content_type=None)
        if not isinstance(payload, dict):
            raise TypeError("GDELT evidence response must be a JSON object")
        articles = payload.get("articles")
        if not isinstance(articles, list):
            raise TypeError("GDELT Article List JSON must contain an articles array")
        return FetchResult(payload=payload, rate_limited=False, attempts=attempt)
    raise AssertionError("unreachable GDELT fetch state")


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

    timeout = aiohttp.ClientTimeout(total=60)
    samples: list[dict[str, Any]] = []
    live_payloads = 0
    rate_limited = 0
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
            result = await fetch_json(session, source)
            if result.rate_limited:
                rate_limited += 1
                samples.append(
                    {
                        "condition_id": market.condition_id,
                        "question": market.question,
                        "source": source,
                        "live_status": "EXTERNAL_RATE_LIMITED",
                        "attempts": result.attempts,
                        "retry_after": result.retry_after,
                    }
                )
                continue
            if result.payload is None:
                raise AssertionError("successful GDELT fetch missing payload")
            live_payloads += 1
            samples.append(
                {
                    "condition_id": market.condition_id,
                    "question": market.question,
                    "source": source,
                    "live_status": "PASS",
                    "attempts": result.attempts,
                    "article_count": len(result.payload["articles"]),
                }
            )

    evidence = {
        "status": "PASS" if live_payloads else "PASS_WITH_EXTERNAL_RATE_LIMIT",
        "mode": "READ_ONLY_DYNAMIC_EVIDENCE",
        "provider_invocations": 0,
        "paper_orders_created": 0,
        "live_orders_created": 0,
        "rendered_contract_samples": len(samples),
        "live_payloads_validated": live_payloads,
        "external_rate_limited": rate_limited,
        "samples": samples,
        "note": (
            "Qualification collection itself does not bypass 429 responses; "
            "it fails before provider invocation when evidence retrieval is unavailable."
        ),
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
        "LIVE_EVIDENCE_TEMPLATE_SMOKE_"
        f"{evidence['status']} "
        f"rendered={evidence['rendered_contract_samples']} "
        f"live={evidence['live_payloads_validated']} "
        f"rate_limited={evidence['external_rate_limited']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
