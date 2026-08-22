"""Append-only SQLite journal for forecasts, evidence provenance, and outcomes."""

from __future__ import annotations

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
            CREATE TABLE IF NOT EXISTS forecasts (
                forecast_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                condition_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                probability_yes TEXT NOT NULL,
                uncertainty TEXT NOT NULL,
                abstain INTEGER NOT NULL,
                issued_at TEXT NOT NULL,
                baseline_probability TEXT,
                rationale TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS forecast_evidence (
                forecast_id TEXT NOT NULL REFERENCES forecasts(forecast_id),
                evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
                ordinal INTEGER NOT NULL,
                PRIMARY KEY (forecast_id, evidence_id)
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
    def _forecast_values(forecast: ProbabilisticForecast) -> tuple[object, ...]:
        return (
            forecast.forecast_id,
            forecast.request_id,
            forecast.condition_id,
            forecast.provider,
            forecast.model,
            str(forecast.probability_yes),
            str(forecast.uncertainty),
            int(forecast.abstain),
            forecast.issued_at.isoformat(),
            (
                str(forecast.baseline_probability)
                if forecast.baseline_probability is not None
                else ""
            ),
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
            for item in request.evidence:
                self._ensure_evidence(item)
            existing = self.connection.execute(
                "SELECT * FROM forecasts WHERE forecast_id = ?",
                (forecast.forecast_id,),
            ).fetchone()
            if existing is not None:
                observed = (
                    existing["forecast_id"],
                    existing["request_id"],
                    existing["condition_id"],
                    existing["provider"],
                    existing["model"],
                    existing["probability_yes"],
                    existing["uncertainty"],
                    existing["abstain"],
                    existing["issued_at"],
                    existing["baseline_probability"] or "",
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
                    forecast_id, request_id, condition_id, provider, model,
                    probability_yes, uncertainty, abstain, issued_at,
                    baseline_probability, rationale, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            self.connection.executemany(
                """
                INSERT INTO forecast_evidence (forecast_id, evidence_id, ordinal)
                VALUES (?, ?, ?)
                """,
                [
                    (forecast.forecast_id, item.evidence_id, ordinal)
                    for ordinal, item in enumerate(request.evidence)
                ],
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
            SELECT f.*, r.outcome_yes
            FROM forecasts AS f
            JOIN resolutions AS r USING (condition_id)
            ORDER BY f.issued_at, f.forecast_id
            """
        ).fetchall()
        results: list[tuple[ProbabilisticForecast, bool]] = []
        for row in rows:
            evidence_rows = self.connection.execute(
                """
                SELECT evidence_id
                FROM forecast_evidence
                WHERE forecast_id = ?
                ORDER BY ordinal
                """,
                (row["forecast_id"],),
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
                metadata=tuple(
                    sorted(json.loads(row["metadata_json"]).items())
                ),
            )
            results.append((forecast, bool(row["outcome_yes"])))
        return results

    def close(self) -> None:
        self.connection.close()
