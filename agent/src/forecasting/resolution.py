"""Automatic, read-only resolution capture for forecast research."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiohttp

from .forecast import utc_now
from .journal import ForecastJournal


@dataclass(frozen=True, slots=True)
class ResolutionObservation:
    condition_id: str
    outcome_yes: bool
    winning_token_id: str
    winning_outcome: str
    observed_at: datetime
    source: str

    @property
    def resolution_id(self) -> str:
        raw = (
            f"polymarket-clob\x1f{self.condition_id}\x1f{self.winning_token_id}"
        ).encode()
        return hashlib.sha256(raw).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class ResolutionFailure:
    condition_id: str
    error: str


@dataclass(frozen=True, slots=True)
class ResolutionCaptureSummary:
    checked: int
    newly_resolved: int
    unresolved: int
    already_recorded: int
    failures: tuple[ResolutionFailure, ...]


class ClobResolutionClient:
    """Public CLOB market-state reader; it never authenticates or places orders."""

    def __init__(self, base_url: str = "https://clob.polymarket.com"):
        self.base_url = base_url.rstrip("/")

    async def fetch_market(self, condition_id: str) -> Mapping[str, Any]:
        condition_id = condition_id.strip()
        if not condition_id:
            raise ValueError("condition_id is required")
        timeout = aiohttp.ClientTimeout(total=20)
        async with (
            aiohttp.ClientSession(timeout=timeout) as session,
            session.get(f"{self.base_url}/markets/{condition_id}") as response,
        ):
            response.raise_for_status()
            payload: Any = await response.json()
        if not isinstance(payload, Mapping):
            raise TypeError("CLOB market response must be an object")
        return payload


def observe_resolution(
    payload: Mapping[str, Any],
    *,
    expected_condition_id: str,
    observed_at: datetime | None = None,
    source: str = "https://clob.polymarket.com/markets/{condition_id}",
) -> ResolutionObservation | None:
    """Return an authoritative binary winner only when a closed market has exactly one."""
    condition_id = str(payload.get("condition_id") or "").strip()
    if not condition_id:
        raise ValueError("CLOB market missing condition_id")
    if condition_id != expected_condition_id:
        raise ValueError("CLOB market condition_id mismatch")
    if payload.get("closed") is not True:
        return None

    tokens = payload.get("tokens")
    if not isinstance(tokens, Sequence) or isinstance(tokens, (str, bytes)):
        raise TypeError("CLOB market tokens must be an array")
    if len(tokens) != 2 or not all(isinstance(token, Mapping) for token in tokens):
        raise ValueError("forecast resolution requires exactly two token records")

    normalized: dict[str, Mapping[str, Any]] = {}
    for token in tokens:
        outcome = str(token.get("outcome") or "").strip().upper()
        if outcome not in {"YES", "NO"}:
            raise ValueError(f"unexpected binary outcome label: {outcome!r}")
        if outcome in normalized:
            raise ValueError(f"duplicate binary outcome label: {outcome}")
        token_id = str(token.get("token_id") or "").strip()
        if not token_id:
            raise ValueError("CLOB market token missing token_id")
        normalized[outcome] = token
    if set(normalized) != {"YES", "NO"}:
        raise ValueError("CLOB market must expose YES and NO tokens")

    winners = [
        (outcome, token)
        for outcome, token in normalized.items()
        if token.get("winner") is True
    ]
    if not winners:
        return None
    if len(winners) != 1:
        raise ValueError("closed market exposes multiple winning tokens")

    winner_outcome, winner = winners[0]
    captured_at = observed_at or utc_now()
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    return ResolutionObservation(
        condition_id=condition_id,
        outcome_yes=winner_outcome == "YES",
        winning_token_id=str(winner["token_id"]),
        winning_outcome=winner_outcome.title(),
        observed_at=captured_at.astimezone(UTC),
        source=source.format(condition_id=condition_id),
    )


def unresolved_condition_ids(journal: ForecastJournal, *, limit: int) -> tuple[str, ...]:
    """Return oldest forecasted conditions that have no recorded resolution."""
    if limit < 1:
        raise ValueError("limit must be positive")
    rows = journal.connection.execute(
        """
        SELECT q.condition_id, MIN(q.issued_at) AS first_issued
        FROM requests AS q
        LEFT JOIN resolutions AS r USING (condition_id)
        WHERE r.condition_id IS NULL
        GROUP BY q.condition_id
        ORDER BY first_issued, q.condition_id
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return tuple(str(row["condition_id"]) for row in rows)


class ResolutionCapture:
    """Matures unresolved forecast requests using public CLOB winner state."""

    def __init__(
        self,
        journal: ForecastJournal,
        *,
        client: ClobResolutionClient | None = None,
        concurrency: int = 8,
    ):
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        self.journal = journal
        self.client = client or ClobResolutionClient()
        self.concurrency = concurrency

    async def capture_once(self, *, limit: int = 100) -> ResolutionCaptureSummary:
        condition_ids = unresolved_condition_ids(self.journal, limit=limit)
        semaphore = asyncio.Semaphore(self.concurrency)

        async def fetch(condition_id: str) -> tuple[str, object]:
            async with semaphore:
                try:
                    payload = await self.client.fetch_market(condition_id)
                    observation = observe_resolution(
                        payload,
                        expected_condition_id=condition_id,
                        observed_at=utc_now(),
                        source=f"{self.client.base_url}/markets/{{condition_id}}",
                    )
                    return condition_id, observation
                except Exception as exc:  # isolated external-contract failure
                    return condition_id, exc

        results = await asyncio.gather(*(fetch(condition_id) for condition_id in condition_ids))
        newly_resolved = 0
        already_recorded = 0
        unresolved = 0
        failures: list[ResolutionFailure] = []

        for condition_id, result in results:
            if isinstance(result, Exception):
                failures.append(
                    ResolutionFailure(
                        condition_id=condition_id,
                        error=f"{type(result).__name__}: {result}",
                    )
                )
                continue
            if result is None:
                unresolved += 1
                continue
            if not isinstance(result, ResolutionObservation):
                failures.append(
                    ResolutionFailure(
                        condition_id=condition_id,
                        error=f"unexpected capture result: {type(result).__name__}",
                    )
                )
                continue
            inserted = self.journal.record_resolution(
                condition_id=result.condition_id,
                outcome_yes=result.outcome_yes,
                resolved_at=result.observed_at,
                resolution_id=result.resolution_id,
            )
            if inserted:
                newly_resolved += 1
            else:
                already_recorded += 1

        return ResolutionCaptureSummary(
            checked=len(condition_ids),
            newly_resolved=newly_resolved,
            unresolved=unresolved,
            already_recorded=already_recorded,
            failures=tuple(failures),
        )
