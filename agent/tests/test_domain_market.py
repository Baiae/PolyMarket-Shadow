import json
from pathlib import Path

import pytest

from domain.market import MarketIdentity, MarketIdentityError


FIXTURES = Path(__file__).parent / "fixtures" / "polymarket"


def test_parses_raw_gamma_binary_market():
    market = json.loads((FIXTURES / "gamma_market.json").read_text())
    identity = MarketIdentity.from_gamma(market, event_id="90177")

    assert identity.gamma_market_id == "703257"
    assert identity.event_id == "90177"
    assert identity.condition_id.startswith("0x747d")
    assert identity.token_for_side("YES") == identity.yes_token_id
    assert identity.token_for_side("no") == identity.no_token_id
    assert identity.side_for_token(identity.yes_token_id) == "YES"


def test_parses_sdk_style_outcomes():
    identity = MarketIdentity.from_gamma({
        "id": "1",
        "condition_id": "0xabc",
        "question": "Test?",
        "outcomes": {
            "yes": {"token_id": "yes-token"},
            "no": {"token_id": "no-token"},
        },
    })
    assert identity.yes_token_id == "yes-token"
    assert identity.no_token_id == "no-token"


def test_rejects_missing_condition_id():
    with pytest.raises(MarketIdentityError):
        MarketIdentity.from_gamma({
            "id": "1",
            "outcomes": ["Yes", "No"],
            "clobTokenIds": '["a","b"]',
        })


def test_rejects_non_binary_market():
    with pytest.raises(MarketIdentityError):
        MarketIdentity.from_gamma({
            "id": "1",
            "conditionId": "0xabc",
            "outcomes": ["A", "B", "C"],
            "clobTokenIds": '["a","b","c"]',
        })


def test_rejects_unknown_token_lookup():
    identity = MarketIdentity.from_gamma({
        "id": "1",
        "conditionId": "0xabc",
        "outcomes": ["Yes", "No"],
        "clobTokenIds": '["a","b"]',
    })
    with pytest.raises(KeyError):
        identity.side_for_token("other")
