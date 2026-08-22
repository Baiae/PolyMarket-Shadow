"""Read-only live evidence collection for calibrated forecasting research."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp

from adapters.polymarket.gamma import GammaAdapter
from domain.market import MarketIdentity
from domain.orderbook import OrderBook

from .forecast import EvidenceItem, ForecastRequest, MarketBaseline, utc_now
from .journal import ForecastJournal
from .provider import ForecastProvider, OpenAICompatibleForecastProvider
from .runner import ForecastExperiment, ForecastFailure


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO timestamp into UTC, rejecting ambiguous naive timestamps."""
    if value is None or not value.strip():
        return None
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def exchange_timestamp(value: int | str) -> datetime:
    """Normalize CLOB second or millisecond timestamps to UTC."""
    raw = int(value)
    if raw <= 0:
        raise ValueError("exchange timestamp must be positive")
    if raw < 10_000_000_000:
        raw *= 1000
    return datetime.fromtimestamp(raw / 1000, tz=UTC)


def _levels(value: Any, *, field: str) -> Sequence[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise TypeError(f"{field} entries must be objects")
    return value


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    condition_id: str
    token_id: str
    captured_at: datetime
    book: OrderBook

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> BookSnapshot:
        condition_id = str(payload.get("market") or "").strip()
        token_id = str(payload.get("asset_id") or "").strip()
        if not condition_id or not token_id:
            raise ValueError("CLOB book missing market or asset_id")
        captured_at = exchange_timestamp(payload.get("timestamp") or 0)
        book = OrderBook(token_id)
        book.apply_snapshot(
            bids=_levels(payload.get("bids", []), field="bids"),
            asks=_levels(payload.get("asks", []), field="asks"),
            timestamp_ms=int(captured_at.timestamp() * 1000),
            book_hash=str(payload.get("hash") or "") or None,
        )
        return cls(condition_id, token_id, captured_at, book)


class ClobSnapshotClient:
    """Public, unauthenticated CLOB order-book snapshot client."""

    def __init__(self, base_url: str = "https://clob.polymarket.com"):
        self.base_url = base_url.rstrip("/")

    async def fetch_books(self, token_ids: Sequence[str]) -> dict[str, BookSnapshot]:
        unique = tuple(dict.fromkeys(token.strip() for token in token_ids if token.strip()))
        if not unique:
            raise ValueError("at least one token_id is required")
        timeout = aiohttp.ClientTimeout(total=20)
        body = [{"token_id": token_id} for token_id in unique]
        async with (
            aiohttp.ClientSession(timeout=timeout) as session,
            session.post(f"{self.base_url}/books", json=body) as response,
        ):
            response.raise_for_status()
            payload: Any = await response.json()
        if not isinstance(payload, list):
            raise TypeError("CLOB /books response must be a list")
        snapshots: dict[str, BookSnapshot] = {}
        for item in payload:
            if not isinstance(item, Mapping):
                raise TypeError("CLOB /books entries must be objects")
            snapshot = BookSnapshot.from_payload(item)
            if snapshot.token_id not in unique:
                raise ValueError("CLOB returned an unrequested token")
            snapshots[snapshot.token_id] = snapshot
        return snapshots


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    provider_name: str
    model_name: str
    base_url: str
    api_key_env: str
    api_key_required: bool = True
    include_market_baseline: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ProviderSpec:
        if "api_key" in value:
            raise ValueError("literal api_key is forbidden; use api_key_env")
        provider_name = str(value.get("provider_name") or "").strip()
        model_name = str(value.get("model_name") or "").strip()
        base_url = str(value.get("base_url") or "").strip()
        api_key_env = str(value.get("api_key_env") or "OPENAI_API_KEY").strip()
        if not provider_name or not model_name or not base_url or not api_key_env:
            raise ValueError("provider_name, model_name, base_url and api_key_env are required")
        api_key_required = value.get("api_key_required", True)
        include_market_baseline = value.get("include_market_baseline", False)
        if not isinstance(api_key_required, bool):
            raise TypeError("api_key_required must be boolean")
        if not isinstance(include_market_baseline, bool):
            raise TypeError("include_market_baseline must be boolean")
        return cls(
            provider_name=provider_name,
            model_name=model_name,
            base_url=base_url,
            api_key_env=api_key_env,
            api_key_required=api_key_required,
            include_market_baseline=include_market_baseline,
        )

    def build(
        self,
        environ: Mapping[str, str] | None = None,
    ) -> OpenAICompatibleForecastProvider:
        values = os.environ if environ is None else environ
        api_key = values.get(self.api_key_env, "").strip()
        if self.api_key_required and not api_key:
            raise ValueError(f"missing provider credential environment variable {self.api_key_env}")
        return OpenAICompatibleForecastProvider(
            provider_name=self.provider_name,
            model_name=self.model_name,
            api_key=api_key or "local-no-secret",
            base_url=self.base_url,
            include_market_baseline=self.include_market_baseline,
        )


def load_provider_specs(path: Path) -> tuple[ProviderSpec, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("provider config must be a non-empty JSON list")
    specs = []
    for item in payload:
        if not isinstance(item, Mapping):
            raise TypeError("provider config entries must be objects")
        specs.append(ProviderSpec.from_mapping(item))
    keys = [(spec.provider_name, spec.model_name) for spec in specs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate provider/model in provider config")
    return tuple(specs)


@dataclass(frozen=True, slots=True)
class EvidenceSpec:
    source: str
    title: str = ""
    published_at: datetime | None = None
    content: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> EvidenceSpec:
        source = str(value.get("source") or "").strip()
        if not source:
            raise ValueError("evidence source is required")
        content_value = value.get("content")
        if content_value is not None and not isinstance(content_value, str):
            raise TypeError("evidence content must be a string")
        content = content_value if content_value is None else content_value.strip()
        if content == "":
            raise ValueError("evidence content cannot be empty")
        if content is None and urlparse(source).scheme not in {"http", "https"}:
            raise ValueError("remote evidence source must use http or https")
        return cls(
            source=source,
            title=str(value.get("title") or "").strip(),
            published_at=parse_iso_datetime(
                str(value.get("published_at") or "") or None
            ),
            content=content,
        )


class EvidenceManifest:
    """Maps market identities to explicitly selected research evidence sources."""

    def __init__(self, entries: Mapping[str, tuple[EvidenceSpec, ...]] | None = None):
        self.entries = dict(entries or {})

    @classmethod
    def empty(cls) -> EvidenceManifest:
        return cls()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> EvidenceManifest:
        markets = payload.get("markets")
        if not isinstance(markets, Mapping):
            raise TypeError("evidence manifest must contain a markets object")
        entries: dict[str, tuple[EvidenceSpec, ...]] = {}
        for key, raw_specs in markets.items():
            if not isinstance(raw_specs, Sequence) or isinstance(raw_specs, (str, bytes)):
                raise TypeError("market evidence entries must be arrays")
            specs = []
            for raw_spec in raw_specs:
                if not isinstance(raw_spec, Mapping):
                    raise TypeError("evidence entries must be objects")
                specs.append(EvidenceSpec.from_mapping(raw_spec))
            entries[str(key)] = tuple(specs)
        return cls(entries)

    @classmethod
    def from_path(cls, path: Path) -> EvidenceManifest:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise TypeError("evidence manifest must be a JSON object")
        return cls.from_mapping(payload)

    def for_market(self, market: MarketIdentity) -> tuple[EvidenceSpec, ...]:
        keys = ("*", market.condition_id, market.gamma_market_id, market.slug)
        result: list[EvidenceSpec] = []
        seen: set[tuple[object, ...]] = set()
        for key in keys:
            if not key:
                continue
            for spec in self.entries.get(key, ()):
                marker = (spec.source, spec.title, spec.published_at, spec.content)
                if marker not in seen:
                    seen.add(marker)
                    result.append(spec)
        return tuple(result)

    def has_market(self, market: MarketIdentity) -> bool:
        return bool(self.for_market(market))


class HttpEvidenceCollector:
    """Freezes operator-selected text/JSON sources before a forecast is issued."""

    def __init__(self, *, max_chars: int = 30_000):
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        self.max_chars = max_chars

    async def collect(self, specs: Sequence[EvidenceSpec]) -> tuple[EvidenceItem, ...]:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            results = [await self._collect_one(session, spec) for spec in specs]
        return tuple(results)

    async def _collect_one(
        self,
        session: aiohttp.ClientSession,
        spec: EvidenceSpec,
    ) -> EvidenceItem:
        if spec.content is not None:
            text = spec.content
        else:
            async with session.get(
                spec.source,
                headers={"User-Agent": "Poly-Shadow/0.3-evidence-collector"},
            ) as response:
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").lower()
                if not (
                    content_type.startswith("text/")
                    or "json" in content_type
                    or "xml" in content_type
                ):
                    raise ValueError(f"unsupported evidence content type: {content_type}")
                text = await response.text(errors="replace")
        text = text[: self.max_chars]
        if not text.strip():
            raise ValueError(f"empty evidence content from {spec.source}")
        retrieved_at = utc_now()
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        raw_id = (
            f"{spec.source}\x1f{retrieved_at.isoformat()}\x1f{content_hash}"
        ).encode()
        evidence_id = f"ev-{hashlib.sha256(raw_id).hexdigest()[:24]}"
        return EvidenceItem.from_text(
            evidence_id=evidence_id,
            source=spec.source,
            retrieved_at=retrieved_at,
            text=text,
            published_at=spec.published_at,
            title=spec.title,
        )


def market_metadata_evidence(
    market: MarketIdentity,
    *,
    retrieved_at: datetime,
    gamma_base_url: str,
) -> EvidenceItem:
    payload = {
        "category": market.category,
        "condition_id": market.condition_id,
        "end_date": market.end_date,
        "event_id": market.event_id,
        "gamma_market_id": market.gamma_market_id,
        "no_token_id": market.no_token_id,
        "question": market.question,
        "slug": market.slug,
        "yes_token_id": market.yes_token_id,
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    raw_id = (
        f"{market.gamma_market_id}\x1f{retrieved_at.isoformat()}\x1f"
        f"{hashlib.sha256(text.encode()).hexdigest()}"
    ).encode()
    evidence_id = f"gamma-{hashlib.sha256(raw_id).hexdigest()[:24]}"
    return EvidenceItem.from_text(
        evidence_id=evidence_id,
        source=f"{gamma_base_url.rstrip('/')}/markets",
        retrieved_at=retrieved_at,
        text=text,
        title="Polymarket Gamma market metadata",
    )


def baseline_from_snapshots(
    market: MarketIdentity,
    snapshots: Mapping[str, BookSnapshot],
    *,
    observed_at: datetime,
    max_age_ms: int,
    source: str,
) -> MarketBaseline:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    yes = snapshots.get(market.yes_token_id)
    no = snapshots.get(market.no_token_id)
    if yes is None or no is None:
        raise ValueError("market requires both YES and NO CLOB snapshots")
    for side, snapshot in (("YES", yes), ("NO", no)):
        if snapshot.condition_id != market.condition_id:
            raise ValueError(f"{side} snapshot condition does not match market")
        if snapshot.captured_at > observed_at:
            raise ValueError(f"{side} snapshot timestamp is in the future")
        age_ms = (observed_at - snapshot.captured_at).total_seconds() * 1000
        if max_age_ms > 0 and age_ms > max_age_ms:
            raise ValueError(f"{side} snapshot is stale")
        if snapshot.book.best_bid is None or snapshot.book.best_ask is None:
            raise ValueError(f"{side} snapshot is not two-sided")
        if snapshot.book.best_bid > snapshot.book.best_ask:
            raise ValueError(f"{side} snapshot is crossed")
    yes_mid = (yes.book.best_bid + yes.book.best_ask) / Decimal(2)
    return MarketBaseline(
        condition_id=market.condition_id,
        probability_yes=yes_mid,
        captured_at=yes.captured_at,
        source=source,
        best_bid=yes.book.best_bid,
        best_ask=yes.book.best_ask,
    )


def make_request_id(
    market: MarketIdentity,
    *,
    issued_at: datetime,
    baseline: MarketBaseline,
    evidence: Sequence[EvidenceItem],
) -> str:
    evidence_hashes = ",".join(item.content_sha256 for item in evidence)
    raw = (
        f"{market.condition_id}\x1f{issued_at.isoformat()}\x1f"
        f"{baseline.probability_yes}\x1f{evidence_hashes}"
    ).encode()
    return f"req-{hashlib.sha256(raw).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class CollectedForecast:
    provider: str
    model: str
    probability_yes: Decimal
    uncertainty: Decimal
    abstain: bool


@dataclass(frozen=True, slots=True)
class CollectedMarket:
    request_id: str
    condition_id: str
    gamma_market_id: str
    slug: str
    question: str
    baseline_probability: Decimal
    evidence_ids: tuple[str, ...]
    forecasts: tuple[CollectedForecast, ...]
    failures: tuple[ForecastFailure, ...]


@dataclass(frozen=True, slots=True)
class CollectionSkip:
    condition_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class CollectionSummary:
    discovered_markets: int
    eligible_markets: int
    collected: tuple[CollectedMarket, ...]
    skipped: tuple[CollectionSkip, ...]

    @property
    def forecast_count(self) -> int:
        return sum(len(item.forecasts) for item in self.collected)

    @property
    def failure_count(self) -> int:
        return sum(len(item.failures) for item in self.collected)


class LiveForecastCollector:
    """Creates bounded out-of-sample research records without any execution path."""

    def __init__(
        self,
        providers: Sequence[ForecastProvider],
        journal: ForecastJournal,
        *,
        gamma: GammaAdapter | None = None,
        clob: ClobSnapshotClient | None = None,
        evidence_collector: HttpEvidenceCollector | None = None,
    ):
        self.gamma = gamma or GammaAdapter()
        self.clob = clob or ClobSnapshotClient()
        self.evidence_collector = evidence_collector or HttpEvidenceCollector()
        self.experiment = ForecastExperiment(list(providers), journal)

    async def collect_once(
        self,
        manifest: EvidenceManifest,
        *,
        sample_count: int = 3,
        discovery_limit: int = 50,
        max_book_age_ms: int = 60_000,
        allow_market_metadata_only: bool = False,
    ) -> CollectionSummary:
        if sample_count < 1 or discovery_limit < 1:
            raise ValueError("sample_count and discovery_limit must be positive")
        markets = await self.gamma.fetch_active_markets(limit=discovery_limit)
        eligible = [
            market
            for market in markets
            if allow_market_metadata_only or manifest.has_market(market)
        ]
        candidate_limit = min(len(eligible), max(sample_count * 4, sample_count))
        candidates = eligible[:candidate_limit]
        token_ids = [token for market in candidates for token in market.token_ids]
        snapshots = await self.clob.fetch_books(token_ids) if token_ids else {}

        collected: list[CollectedMarket] = []
        skipped: list[CollectionSkip] = []
        for market in candidates:
            if len(collected) >= sample_count:
                break
            try:
                resolves_at = parse_iso_datetime(market.end_date)
                if resolves_at is None or resolves_at <= utc_now():
                    raise ValueError("market lacks a future resolution timestamp")
                observed_at = utc_now()
                baseline = baseline_from_snapshots(
                    market,
                    snapshots,
                    observed_at=observed_at,
                    max_age_ms=max_book_age_ms,
                    source=f"{self.clob.base_url}/books",
                )
                specs = manifest.for_market(market)
                if not specs and not allow_market_metadata_only:
                    raise ValueError("no external evidence configured for market")
                metadata = market_metadata_evidence(
                    market,
                    retrieved_at=utc_now(),
                    gamma_base_url=self.gamma.base_url,
                )
                external = await self.evidence_collector.collect(specs)
                evidence = (metadata, *external)
                issued_at = utc_now()
                request = ForecastRequest.create(
                    request_id=make_request_id(
                        market,
                        issued_at=issued_at,
                        baseline=baseline,
                        evidence=evidence,
                    ),
                    condition_id=market.condition_id,
                    question=market.question,
                    resolves_at=resolves_at,
                    evidence=evidence,
                    baseline=baseline,
                    issued_at=issued_at,
                )
                result = await self.experiment.run(request)
            except (aiohttp.ClientError, TypeError, ValueError) as exc:
                skipped.append(
                    CollectionSkip(
                        condition_id=market.condition_id,
                        reason=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            collected.append(
                CollectedMarket(
                    request_id=request.request_id,
                    condition_id=market.condition_id,
                    gamma_market_id=market.gamma_market_id,
                    slug=market.slug,
                    question=market.question,
                    baseline_probability=baseline.probability_yes,
                    evidence_ids=tuple(item.evidence_id for item in evidence),
                    forecasts=tuple(
                        CollectedForecast(
                            provider=forecast.provider,
                            model=forecast.model,
                            probability_yes=forecast.probability_yes,
                            uncertainty=forecast.uncertainty,
                            abstain=forecast.abstain,
                        )
                        for forecast in result.forecasts
                    ),
                    failures=result.failures,
                )
            )

        return CollectionSummary(
            discovered_markets=len(markets),
            eligible_markets=len(eligible),
            collected=tuple(collected),
            skipped=tuple(skipped),
        )
