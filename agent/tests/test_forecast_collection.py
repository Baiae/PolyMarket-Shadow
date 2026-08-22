from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from domain.market import MarketIdentity
from forecasting.collection import (
    BookSnapshot,
    ClobSnapshotClient,
    EvidenceManifest,
    HttpEvidenceCollector,
    LiveForecastCollector,
    ProviderSpec,
    baseline_from_snapshots,
)
from forecasting.forecast import ProbabilisticForecast, make_forecast_id
from forecasting.journal import ForecastJournal


def _market(now: datetime) -> MarketIdentity:
    return MarketIdentity(
        gamma_market_id="g1",
        condition_id="0xcondition",
        yes_token_id="yes-token",
        no_token_id="no-token",
        question="Will the test event happen?",
        slug="test-event",
        end_date=(now + timedelta(days=30)).isoformat(),
    )


def _payload(token_id: str, *, captured_at: datetime) -> dict:
    return {
        "market": "0xcondition",
        "asset_id": token_id,
        "timestamp": str(int(captured_at.timestamp() * 1000)),
        "hash": f"hash-{token_id}",
        "bids": [{"price": "0.44", "size": "100"}],
        "asks": [{"price": "0.46", "size": "100"}],
    }


def test_book_snapshot_builds_two_sided_market_baseline():
    now = datetime.now(UTC)
    market = _market(now)
    snapshots = {
        token: BookSnapshot.from_payload(_payload(token, captured_at=now))
        for token in market.token_ids
    }
    baseline = baseline_from_snapshots(
        market,
        snapshots,
        observed_at=now,
        max_age_ms=60_000,
        source="https://clob.polymarket.com/books",
    )
    assert baseline.probability_yes == Decimal("0.45")
    assert baseline.best_bid == Decimal("0.44")
    assert baseline.best_ask == Decimal("0.46")


def test_baseline_rejects_wrong_condition_and_stale_snapshot():
    now = datetime.now(UTC)
    market = _market(now)
    yes = BookSnapshot.from_payload(
        _payload(market.yes_token_id, captured_at=now - timedelta(minutes=2))
    )
    no_payload = _payload(market.no_token_id, captured_at=now)
    no_payload["market"] = "0xwrong"
    no = BookSnapshot.from_payload(no_payload)
    with pytest.raises(ValueError, match="stale"):
        baseline_from_snapshots(
            market,
            {market.yes_token_id: yes, market.no_token_id: no},
            observed_at=now,
            max_age_ms=60_000,
            source="clob",
        )


def test_provider_spec_forbids_literal_secrets_and_supports_local_endpoint():
    with pytest.raises(ValueError, match="literal api_key"):
        ProviderSpec.from_mapping(
            {
                "provider_name": "bad",
                "model_name": "model",
                "base_url": "http://localhost/v1",
                "api_key": "secret",
            }
        )
    spec = ProviderSpec.from_mapping(
        {
            "provider_name": "local",
            "model_name": "model",
            "base_url": "http://127.0.0.1:9999/v1",
            "api_key_env": "LOCAL_KEY",
            "api_key_required": False,
        }
    )
    provider = spec.build({})
    assert provider.provider_name == "local"
    assert provider.model_name == "model"


@pytest.mark.asyncio
async def test_static_evidence_is_frozen_with_hash_and_manifest_selection():
    now = datetime.now(UTC)
    market = _market(now)
    manifest = EvidenceManifest.from_mapping(
        {
            "markets": {
                "*": [{"source": "operator:common", "content": "common fact"}],
                market.slug: [
                    {
                        "source": "operator:specific",
                        "content": "specific fact",
                        "title": "Specific source",
                    }
                ],
            }
        }
    )
    specs = manifest.for_market(market)
    assert len(specs) == 2
    items = await HttpEvidenceCollector().collect(specs)
    assert [item.content for item in items] == ["common fact", "specific fact"]
    assert all(len(item.content_sha256) == 64 for item in items)


class FakeGamma:
    base_url = "https://gamma.example"

    def __init__(self, market):
        self.market = market

    async def fetch_active_markets(self, *, limit):
        del limit
        return [self.market]


class FakeClob:
    base_url = "https://clob.example"

    def __init__(self, snapshots):
        self.snapshots = snapshots

    async def fetch_books(self, token_ids):
        assert set(token_ids) == set(self.snapshots)
        return self.snapshots


class GoodProvider:
    provider_name = "local"
    model_name = "good"

    async def forecast(self, request):
        return ProbabilisticForecast(
            forecast_id=make_forecast_id(
                request.request_id,
                self.provider_name,
                self.model_name,
            ),
            request_id=request.request_id,
            condition_id=request.condition_id,
            provider=self.provider_name,
            model=self.model_name,
            probability_yes="0.63",
            uncertainty="0.25",
            abstain=False,
            issued_at=request.issued_at,
            evidence_ids=tuple(item.evidence_id for item in request.evidence),
            baseline_probability=request.baseline.probability_yes,
        )


class FailingProvider:
    provider_name = "remote"
    model_name = "down"

    async def forecast(self, request):
        del request
        raise RuntimeError("provider unavailable")


@pytest.mark.asyncio
async def test_live_collector_journals_request_success_and_provider_failure():
    now = datetime.now(UTC)
    market = _market(now)
    snapshots = {
        token: BookSnapshot.from_payload(_payload(token, captured_at=now))
        for token in market.token_ids
    }
    manifest = EvidenceManifest.from_mapping(
        {
            "markets": {
                market.slug: [
                    {"source": "operator:test", "content": "independent evidence"}
                ]
            }
        }
    )
    journal = ForecastJournal()
    collector = LiveForecastCollector(
        [GoodProvider(), FailingProvider()],
        journal,
        gamma=FakeGamma(market),
        clob=FakeClob(snapshots),
    )
    summary = await collector.collect_once(
        manifest,
        sample_count=1,
        discovery_limit=1,
        max_book_age_ms=60_000,
    )
    assert len(summary.collected) == 1
    assert summary.forecast_count == 1
    assert summary.failure_count == 1
    assert journal.request_count() == 1
    assert journal.failure_count() == 1


@pytest.mark.asyncio
async def test_all_provider_failures_still_preserve_issuance_record():
    now = datetime.now(UTC)
    market = _market(now)
    snapshots = {
        token: BookSnapshot.from_payload(_payload(token, captured_at=now))
        for token in market.token_ids
    }
    manifest = EvidenceManifest.from_mapping(
        {
            "markets": {
                market.slug: [{"source": "operator:test", "content": "evidence"}]
            }
        }
    )
    journal = ForecastJournal()
    collector = LiveForecastCollector(
        [FailingProvider()],
        journal,
        gamma=FakeGamma(market),
        clob=FakeClob(snapshots),
    )
    summary = await collector.collect_once(
        manifest,
        sample_count=1,
        discovery_limit=1,
        max_book_age_ms=60_000,
    )
    assert len(summary.collected) == 1
    assert summary.forecast_count == 0
    assert summary.failure_count == 1
    assert journal.request_count() == 1
    assert journal.failure_count() == 1


@pytest.mark.asyncio
async def test_clob_client_rejects_empty_token_set():
    client = ClobSnapshotClient()
    with pytest.raises(ValueError, match="token_id"):
        await client.fetch_books([])
