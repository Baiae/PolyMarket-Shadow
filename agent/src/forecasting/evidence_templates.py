"""Deterministic market-specific evidence source expansion."""

from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import quote_plus, urlparse

from domain.market import MarketIdentity

from .collection import EvidenceManifest, EvidenceSpec

_TEMPLATE_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’.-]*")
_TITLE_PHRASE_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9'’.-]+(?:\s+[A-Z][A-Za-z0-9'’.-]+)+)\b"
)
_DIGIT_COMMA_RE = re.compile(r"(?<=\d),(?=\d)")

_ALLOWED_SOURCE_FIELDS = frozenset(
    {
        "condition_id",
        "gamma_market_id",
        "slug",
        "question",
        "gdelt_query",
    }
)

_LEADING_QUESTION_WORDS = frozenset(
    {
        "are",
        "can",
        "could",
        "did",
        "do",
        "does",
        "had",
        "has",
        "have",
        "how",
        "is",
        "should",
        "was",
        "were",
        "what",
        "when",
        "where",
        "who",
        "why",
        "will",
        "would",
    }
)

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "before",
        "between",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "over",
        "should",
        "than",
        "that",
        "the",
        "their",
        "there",
        "this",
        "to",
        "under",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
    }
)


def _strip_leading_question_words(question: str) -> str:
    words = question.strip().split()
    while words and words[0].strip("?!.,:;").lower() in _LEADING_QUESTION_WORDS:
        words.pop(0)
    return " ".join(words)


def _content_tokens(question: str) -> list[str]:
    normalized = _DIGIT_COMMA_RE.sub("", question)
    result: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN_RE.findall(normalized):
        cleaned = token.strip(".'’-")
        lowered = cleaned.lower()
        if not cleaned or lowered in _STOPWORDS:
            continue
        if len(cleaned) < 3 and not cleaned.isdigit():
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(cleaned)
    return result


def gdelt_query_expression(question: str) -> str:
    """Create one stable, reasonably specific GDELT query from a market question."""
    stripped = _strip_leading_question_words(question)
    if not stripped:
        raise ValueError("market question does not contain searchable terms")

    tokens = _content_tokens(stripped)
    if not tokens:
        raise ValueError("market question does not contain searchable terms")

    title_match = _TITLE_PHRASE_RE.search(stripped)
    anchor: str
    consumed: set[str]
    if title_match is not None:
        phrase = title_match.group(0).strip()
        anchor = f'"{phrase}"'
        consumed = {item.lower() for item in _TOKEN_RE.findall(phrase)}
    else:
        anchor = tokens[0]
        consumed = {tokens[0].lower()}

    tail = [item for item in tokens if item.lower() not in consumed][:4]
    if not tail:
        return anchor
    return f"{anchor} ({' OR '.join(tail)})"


def _source_values(market: MarketIdentity) -> dict[str, str]:
    values = {
        "condition_id": market.condition_id,
        "gamma_market_id": market.gamma_market_id,
        "slug": market.slug,
        "question": market.question,
        "gdelt_query": gdelt_query_expression(market.question),
    }
    return {key: quote_plus(str(value)) for key, value in values.items()}


def render_source_template(template: str, market: MarketIdentity) -> str:
    """Expand only explicit URL-encoded market placeholders in an evidence URL."""
    fields = set(_TEMPLATE_RE.findall(template))
    unknown = fields - _ALLOWED_SOURCE_FIELDS
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ValueError(f"unsupported evidence template field(s): {joined}")
    values = _source_values(market)
    rendered = _TEMPLATE_RE.sub(lambda match: values[match.group(1)], template)
    parsed = urlparse(rendered)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("rendered evidence source must be an absolute http(s) URL")
    return rendered


class TemplatedEvidenceManifest:
    """Render frozen EvidenceManifest source URLs from pre-forecast market identity."""

    def __init__(self, manifest: EvidenceManifest):
        self.manifest = manifest

    def for_market(self, market: MarketIdentity) -> tuple[EvidenceSpec, ...]:
        rendered: list[EvidenceSpec] = []
        for spec in self.manifest.for_market(market):
            if spec.content is not None:
                if _TEMPLATE_RE.search(spec.source):
                    raise ValueError(
                        "evidence source templates are only supported for remote evidence"
                    )
                rendered.append(spec)
                continue
            rendered.append(
                replace(spec, source=render_source_template(spec.source, market))
            )
        return tuple(rendered)

    def has_market(self, market: MarketIdentity) -> bool:
        return bool(self.for_market(market))
