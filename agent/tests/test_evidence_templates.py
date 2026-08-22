from urllib.parse import parse_qs, unquote_plus, urlparse

import pytest

from domain.market import MarketIdentity
from forecasting.collection import EvidenceManifest
from forecasting.evidence_templates import (
    TemplatedEvidenceManifest,
    gdelt_query_expression,
    render_source_template,
)


def market(question: str, *, suffix: str = "one") -> MarketIdentity:
    return MarketIdentity(
        gamma_market_id=f"gamma-{suffix}",
        condition_id=f"condition-{suffix}",
        yes_token_id=f"yes-{suffix}",
        no_token_id=f"no-{suffix}",
        question=question,
        event_id=f"event-{suffix}",
        slug=f"slug-{suffix}",
    )


def test_gdelt_query_prefers_named_phrase_and_relevant_tail_terms():
    expression = gdelt_query_expression(
        "Will Gavin Newsom win the 2028 Democratic nomination?"
    )
    assert expression == '"Gavin Newsom" (win OR 2028 OR Democratic OR nomination)'


def test_gdelt_query_uses_first_content_term_as_anchor_without_named_phrase():
    expression = gdelt_query_expression(
        "Will bitcoin exceed 100,000 dollars before September 2026?"
    )
    assert expression == "bitcoin (exceed OR 100000 OR dollars OR September)"


def test_rendered_gdelt_source_is_market_specific_and_url_encoded():
    template = (
        "https://api.gdeltproject.org/api/v2/doc/doc?"
        "query={gdelt_query}&mode=artlist&maxrecords=25&timespan=30d&format=json"
    )
    first = render_source_template(
        template,
        market("Will Gavin Newsom win the 2028 Democratic nomination?"),
    )
    second = render_source_template(
        template,
        market("Will bitcoin exceed 100,000 dollars before September 2026?", suffix="two"),
    )
    assert first != second
    parsed = parse_qs(urlparse(first).query)
    assert parsed["mode"] == ["artlist"]
    assert parsed["format"] == ["json"]
    assert parsed["timespan"] == ["30d"]
    assert unquote_plus(parsed["query"][0]) == (
        '"Gavin Newsom" (win OR 2028 OR Democratic OR nomination)'
    )


def test_manifest_renders_wildcard_template_per_market_and_preserves_static_sources():
    manifest = EvidenceManifest.from_mapping(
        {
            "markets": {
                "*": [
                    {
                        "source": (
                            "https://api.gdeltproject.org/api/v2/doc/doc?"
                            "query={gdelt_query}&mode=artlist&maxrecords=25&"
                            "timespan=30d&format=json"
                        ),
                        "title": "GDELT recent news search",
                    },
                    {
                        "source": "https://example.com/reference.json",
                        "title": "Static reference",
                    },
                ]
            }
        }
    )
    wrapped = TemplatedEvidenceManifest(manifest)
    specs = wrapped.for_market(
        market("Will Xi Jinping leave office before 2027?")
    )
    assert len(specs) == 2
    assert "{gdelt_query}" not in specs[0].source
    assert specs[0].source.startswith("https://api.gdeltproject.org/")
    assert specs[1].source == "https://example.com/reference.json"
    assert wrapped.has_market(market("Will Xi Jinping leave office before 2027?"))


def test_unknown_template_field_is_rejected():
    with pytest.raises(ValueError, match="unsupported evidence template field"):
        render_source_template(
            "https://example.com/?q={model_generated_query}",
            market("Will the Fed cut rates in September?"),
        )


def test_templates_are_not_allowed_for_inline_content_specs():
    manifest = EvidenceManifest.from_mapping(
        {
            "markets": {
                "*": [
                    {
                        "source": "operator:{condition_id}",
                        "title": "Inline fixture",
                        "content": "fixed text",
                    }
                ]
            }
        }
    )
    with pytest.raises(ValueError, match="only supported for remote evidence"):
        TemplatedEvidenceManifest(manifest).for_market(
            market("Will the Fed cut rates in September?")
        )


def test_empty_or_non_searchable_question_is_rejected():
    with pytest.raises(ValueError, match="searchable terms"):
        gdelt_query_expression("Will it be?")
