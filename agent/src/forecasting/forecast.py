"""Canonical forecast, evidence, and market-baseline records."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

ZERO = Decimal(0)
ONE = Decimal(1)


def utc_now() -> datetime:
    return datetime.now(UTC)


def probability(value: Decimal | str | float) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid probability: {value!r}") from exc
    if result < ZERO or result > ONE:
        raise ValueError(f"probability outside [0,1]: {result}")
    return result


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value


def make_forecast_id(request_id: str, provider: str, model: str) -> str:
    raw = f"{request_id}\x1f{provider}\x1f{model}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: str
    source: str
    retrieved_at: datetime
    content: str
    content_sha256: str
    published_at: datetime | None = None
    title: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id is required")
        if not self.source.strip():
            raise ValueError("evidence source is required")
        _aware(self.retrieved_at)
        if self.published_at is not None:
            _aware(self.published_at)
            if self.published_at > self.retrieved_at:
                raise ValueError("evidence cannot be published after retrieval")
        digest = self.content_sha256.lower()
        expected = hashlib.sha256(self.content.encode()).hexdigest()
        if digest != expected:
            raise ValueError("content_sha256 does not match evidence content")

    @classmethod
    def from_text(
        cls,
        *,
        evidence_id: str,
        source: str,
        retrieved_at: datetime,
        text: str,
        published_at: datetime | None = None,
        title: str = "",
    ) -> EvidenceItem:
        digest = hashlib.sha256(text.encode()).hexdigest()
        return cls(
            evidence_id=evidence_id,
            source=source,
            retrieved_at=retrieved_at,
            content=text,
            content_sha256=digest,
            published_at=published_at,
            title=title,
        )


@dataclass(frozen=True, slots=True)
class MarketBaseline:
    condition_id: str
    probability_yes: Decimal
    captured_at: datetime
    source: str
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.condition_id.strip():
            raise ValueError("condition_id is required")
        object.__setattr__(self, "probability_yes", probability(self.probability_yes))
        _aware(self.captured_at)
        if not self.source.strip():
            raise ValueError("baseline source is required")
        if self.best_bid is not None:
            object.__setattr__(self, "best_bid", probability(self.best_bid))
        if self.best_ask is not None:
            object.__setattr__(self, "best_ask", probability(self.best_ask))
        if (
            self.best_bid is not None
            and self.best_ask is not None
            and self.best_bid > self.best_ask
        ):
            raise ValueError("baseline best bid cannot exceed best ask")


@dataclass(frozen=True, slots=True)
class ForecastRequest:
    request_id: str
    condition_id: str
    question: str
    resolves_at: datetime | None
    issued_at: datetime
    evidence: tuple[EvidenceItem, ...] = ()
    baseline: MarketBaseline | None = None

    def __post_init__(self) -> None:
        if not self.request_id.strip():
            raise ValueError("request_id is required")
        if not self.condition_id.strip():
            raise ValueError("condition_id is required")
        if not self.question.strip():
            raise ValueError("question is required")
        _aware(self.issued_at)
        if self.resolves_at is not None:
            _aware(self.resolves_at)
            if self.resolves_at <= self.issued_at:
                raise ValueError("forecast must be issued before resolution time")
        if self.baseline is not None:
            if self.baseline.condition_id != self.condition_id:
                raise ValueError("baseline condition does not match request")
            if self.baseline.captured_at > self.issued_at:
                raise ValueError("baseline cannot be captured after forecast issuance")
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evidence_id in request")
        if any(item.retrieved_at > self.issued_at for item in self.evidence):
            raise ValueError("evidence cannot be retrieved after forecast issuance")

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        condition_id: str,
        question: str,
        resolves_at: datetime | None = None,
        evidence: Iterable[EvidenceItem] = (),
        baseline: MarketBaseline | None = None,
        issued_at: datetime | None = None,
    ) -> ForecastRequest:
        return cls(
            request_id=request_id,
            condition_id=condition_id,
            question=question,
            resolves_at=resolves_at,
            issued_at=issued_at or utc_now(),
            evidence=tuple(evidence),
            baseline=baseline,
        )


@dataclass(frozen=True, slots=True)
class ProbabilisticForecast:
    forecast_id: str
    request_id: str
    condition_id: str
    provider: str
    model: str
    probability_yes: Decimal
    uncertainty: Decimal
    abstain: bool
    issued_at: datetime
    evidence_ids: tuple[str, ...] = ()
    baseline_probability: Decimal | None = None
    rationale: str = ""
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.forecast_id.strip() or not self.request_id.strip():
            raise ValueError("forecast_id and request_id are required")
        if not self.condition_id.strip():
            raise ValueError("condition_id is required")
        if not self.provider.strip() or not self.model.strip():
            raise ValueError("provider and model are required")
        object.__setattr__(self, "probability_yes", probability(self.probability_yes))
        object.__setattr__(self, "uncertainty", probability(self.uncertainty))
        if self.baseline_probability is not None:
            object.__setattr__(
                self,
                "baseline_probability",
                probability(self.baseline_probability),
            )
        _aware(self.issued_at)
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("duplicate evidence_ids in forecast")
        keys = [key for key, _ in self.metadata]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate metadata key in forecast")

    @property
    def forecaster_key(self) -> str:
        return f"{self.provider}:{self.model}"
