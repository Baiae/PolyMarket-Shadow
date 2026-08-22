"""Append-only SQLite journal for requests, forecasts, provenance, and outcomes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .forecast import EvidenceItem, ForecastRequest, ProbabilisticForecast


class ForecastJournal:
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS evidence (
                evidence_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                published_at TEXT,
                content TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                title TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS requests (
                request_id TEXT PRIMARY KEY,
                condition_id TEXT NOT NULL,
                question TEXT NOT NULL,
                resolves_at TEXT,
                issued_at TEXT NOT NULL,
                baseline_probability TEXT,
                baseline_captured_at TEXT,
                baseline_source TEXT,
                baseline_best_bid TEXT,
                baseline_best_ask TEXT
            );
            CREATE TABLE IF NOT EXISTS request_evidence (
                request_id TEXT NOT NULL REFERENCES requests(request_id),
                evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
                ordinal INTEGER NOT NULL,
                PRIMARY KEY (request_id, evidence_id)
            );
            CREATE TABLE IF NOT EXISTS forecasts (
                forecast_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL REFERENCES requests(request_id),
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                probability_yes TEXT NOT NULL,
                uncertainty TEXT NOT NULL,
                abstain INTEGER NOT NULL,
                rationale TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS forecast_failures (
                failure_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL REFERENCES requests(request_id),
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                error TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS resolutions (
                condition_id TEXT PRIMARY KEY,
                outcome_yes INTEGER NOT NULL,
                resolved_at TEXT NOT NULL,
                resolution_id TEXT NOT NULL UNIQUE
            );
            """
        )
        self.connection.commit()

    @staticmethod
    def _evidence_values(item: EvidenceItem) -> tuple[object, ...]:
        return (
            item.evidence_id,
            item.source,
            item.retrieved_at.isoformat(),
            item.published_at.isoformat() if item.published_at else "",
            item.content,
            item.content_sha256,
            item.title,
        )

    @staticmethod
    def _request_values(request: ForecastRequest) -> tuple[object, ...]:
        baseline = request.baseline
        return (
            request.request_id,
            request.condition_id,
            request.question,
            request.resolves_at.isoformat() if request.resolves_at else "",
            request.issued_at.isoformat(),
            str(baseline.probability_yes) if baseline else "",
            baseline.captured_at.isoformat() if baseline else "",
            baseline.source if baseline else "",
            str(baseline.best_bid) if baseline and baseline.best_bid is not None else "",
            str(baseline.best_ask) if baseline and baseline.best_ask is not None else "",
        )

    @staticmethod
    def _forecast_values(forecast: ProbabilisticForecast) -> tuple[object, ...]:
        return (
            forecast.forecast_id,
            forecast.request_id,
            forecast.provider,
            forecast.model,
            str(forecast.probability_yes),
            str(forecast.uncertainty),
            int(forecast.abstain),
            forecast.rationale,
            json.dumps(
                dict(forecast.metadata),
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    def _ensure_evidence(self, item: EvidenceItem) -> None:
        values = self._evidence_values(item)
        existing = self.connection.execute(
            "SELECT * FROM evidence WHERE evidence_id = ?",
            (item.evidence_id,),
        ).fetchone()
        if existing is None:
            self.connection.execute(
                """
                INSERT INTO evidence (
                    evidence_id, source, retrieved_at, published_at,
                    content, content_sha256, title
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            return
        observed = (
            existing["evidence_id"],
            existing["source"],
            existing["retrieved_at"],
            existing["published_at"] or "",
            existing["content"],
            existing["content_sha256"],
            existing["title"],
        )
        if observed != values:
            raise ValueError(f"evidence_id {item.evidence_id!r} changed provenance")

    def _ensure_request(self, request: ForecastRequest) -> None:
        for item in request.evidence:
            self._ensure_evidence(item)
        values = self._request_values(request)
        existing = self.connection.execute(
            "SELECT * FROM requests WHERE request_id = ?",
            (request.request_id,),
        ).fetchone()
        if existing is None:
            self.connection.execute(
                """
                INSERT INTO requests (
                    request_id, condition_id, question, resolves_at, issued_at,
                    baseline_probability, baseline_captured_at, baseline_source,
                    baseline_best_bid, baseline_best_ask
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            self.connection.executemany(
                """
                INSERT INTO request_evidence (request_id, evidence_id, ordinal)
                VALUES (?, ?, ?)
                """,
                [
                    (request.request_id, item.evidence_id, ordinal)
                    for ordinal, item in enumerate(request.evidence)
                ],
            )
            return

        observed = (
            existing["request_id"],
            existing["condition_id"],
            existing["question"],
            existing["resolves_at"] or "",
            existing["issued_at"],
            existing["baseline_probability"] or "",
            existing["baseline_captured_at"] or "",
            existing["baseline_source"] or "",
            existing["baseline_best_bid"] or "",
            existing["baseline_best_ask"] or "",
        )
        if observed != values:
            raise ValueError(f"request_id {request.request_id!r} changed contents")
        evidence_rows = self.connection.execute(
            """
            SELECT evidence_id
            FROM request_evidence
            WHERE request_id = ?
            ORDER BY ordinal
            """,
            (request.request_id,),
        ).fetchall()
        observed_ids = tuple(row["evidence_id"] for row in evidence_rows)
        expected_ids = tuple(item.evidence_id for item in request.evidence)
        if observed_ids != expected_ids:
            raise ValueError(f"request_id {request.request_id!r} changed evidence")

    def record_request(self, request: ForecastRequest) -> bool:
        with self.connection:
            existing = self.connection.execute(
                "SELECT 1 FROM requests WHERE request_id = ?",
                (request.request_id,),
            ).fetchone()
            self._ensure_request(request)
        return existing is None

    def record_forecast(
        self,
        request: ForecastRequest,
        forecast: ProbabilisticForecast,
    ) -> bool:
        if request.request_id != forecast.request_id:
            raise ValueError("request/forecast request_id mismatch")
        if request.condition_id != forecast.condition_id:
            raise ValueError("request/forecast condition mismatch")
        if request.issued_at != forecast.issued_at:
            raise ValueError("forecast issued_at does not match request")
        request_ids = tuple(item.evidence_id for item in request.evidence)
        if request_ids != forecast.evidence_ids:
            raise ValueError("forecast evidence_ids do not match request evidence")
        baseline = request.baseline.probability_yes if request.baseline else None
        if baseline != forecast.baseline_probability:
            raise ValueError("forecast baseline does not match issuance baseline")

        values = self._forecast_values(forecast)
        with self.connection:
            self._ensure_request(request)
            existing = self.connection.execute(
                "SELECT * FROM forecasts WHERE forecast_id = ?",
                (forecast.forecast_id,),
            ).fetchone()
            if existing is not None:
                observed = (
                    existing["forecast_id"],
                    existing["request_id"],
                    existing["provider"],
                    existing["model"],
                    existing["probability_yes"],
                    existing["uncertainty"],
                    existing["abstain"],
                    existing["rationale"],
                    existing["metadata_json"],
                )
                if observed != values:
                    raise ValueError(
                        f"forecast_id {forecast.forecast_id!r} changed contents"
                    )
                return False

            self.connection.execute(
                """
                INSERT INTO forecasts (
                    forecast_id, request_id, provider, model,
                    probability_yes, uncertainty, abstain,
                    rationale, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        return True

    def record_failure(
        self,
        request: ForecastRequest,
        *,
        provider: str,
        model: str,
        error: str,
        recorded_at: datetime,
    ) -> bool:
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        raw = f"{request.request_id}\x1f{provider}\x1f{model}".encode()
        failure_id = hashlib.sha256(raw).hexdigest()[:24]
        values = (
            failure_id,
            request.request_id,
            provider,
            model,
            error,
            recorded_at.isoformat(),
        )
        with self.connection:
            self._ensure_request(request)
            existing = self.connection.execute(
                "SELECT * FROM forecast_failures WHERE failure_id = ?",
                (failure_id,),
            ).fetchone()
            if existing is not None:
                observed = (
                    existing["failure_id"],
                    existing["request_id"],
                    existing["provider"],
                    existing["model"],
                    existing["error"],
                    existing["recorded_at"],
                )
                if observed != values:
                    raise ValueError(f"failure_id {failure_id!r} changed contents")
                return False
            self.connection.execute(
                """
                INSERT INTO forecast_failures (
                    failure_id, request_id, provider, model, error, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        return True

    def record_resolution(
        self,
        *,
        condition_id: str,
        outcome_yes: bool,
        resolved_at: datetime,
        resolution_id: str,
    ) -> bool:
        if resolved_at.tzinfo is None or resolved_at.utcoffset() is None:
            raise ValueError("resolved_at must be timezone-aware")
        values = (
            condition_id,
            int(outcome_yes),
            resolved_at.isoformat(),
            resolution_id,
        )
        with self.connection:
            existing = self.connection.execute(
                "SELECT * FROM resolutions WHERE condition_id = ?",
                (condition_id,),
            ).fetchone()
            if existing is not None:
                observed = (
                    existing["condition_id"],
                    existing["outcome_yes"],
                    existing["resolved_at"],
                    existing["resolution_id"],
                )
                if observed != values:
                    raise ValueError(
                        f"condition {condition_id!r} resolution changed"
                    )
                return False
            self.connection.execute(
                """
                INSERT INTO resolutions (
                    condition_id, outcome_yes, resolved_at, resolution_id
                ) VALUES (?, ?, ?, ?)
                """,
                values,
            )
        return True

    def resolved_forecasts(
        self,
    ) -> list[tuple[ProbabilisticForecast, bool]]:
        rows = self.connection.execute(
            """
            SELECT f.*, q.condition_id, q.issued_at,
                   q.baseline_probability, r.outcome_yes
            FROM forecasts AS f
            JOIN requests AS q USING (request_id)
            JOIN resolutions AS r USING (condition_id)
            ORDER BY q.issued_at, f.forecast_id
            """
        ).fetchall()
        results: list[tuple[ProbabilisticForecast, bool]] = []
        for row in rows:
            evidence_rows = self.connection.execute(
                """
                SELECT evidence_id
                FROM request_evidence
                WHERE request_id = ?
                ORDER BY ordinal
                """,
                (row["request_id"],),
            ).fetchall()
            baseline = (
                row["baseline_probability"]
                if row["baseline_probability"] not in (None, "")
                else None
            )
            forecast = ProbabilisticForecast(
                forecast_id=row["forecast_id"],
                request_id=row["request_id"],
                condition_id=row["condition_id"],
                provider=row["provider"],
                model=row["model"],
                probability_yes=row["probability_yes"],
                uncertainty=row["uncertainty"],
                abstain=bool(row["abstain"]),
                issued_at=datetime.fromisoformat(row["issued_at"]),
                evidence_ids=tuple(item["evidence_id"] for item in evidence_rows),
                baseline_probability=baseline,
                rationale=row["rationale"],
                metadata=tuple(sorted(json.loads(row["metadata_json"]).items())),
            )
            results.append((forecast, bool(row["outcome_yes"])))
        return results

    def request_count(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) AS n FROM requests").fetchone()
        return int(row["n"])

    def failure_count(self) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS n FROM forecast_failures"
        ).fetchone()
        return int(row["n"])

    def close(self) -> None:
        self.connection.close()
