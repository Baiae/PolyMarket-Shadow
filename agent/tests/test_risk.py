from decimal import Decimal

from accounting.ledger import Ledger
from domain.orders import Fill
from risk import RiskManager


def fill():
    return Fill(
        fill_id="f1",
        condition_id="0xabc",
        token_id="yes",
        side="YES",
        requested_shares=Decimal("100"),
        filled_shares=Decimal("100"),
        average_price=Decimal("0.5"),
        gross_cost=Decimal("50"),
        fee=Decimal("0"),
        total_cost=Decimal("50"),
        timestamp_ms=1,
        source="TEST",
    )


def test_drawdown_is_derived_from_ledger_equity():
    ledger = Ledger(initial_cash="100")
    ledger.record_fill(fill())
    risk = RiskManager(ledger, max_drawdown_pct="0.30")
    assert risk.evaluate({"yes": Decimal("0.5")}) is False
    assert risk.evaluate({"yes": Decimal("0.2")}) is True
    assert risk.is_killed is True
    assert risk.stats["equity"] == "70.0"


def test_manual_kill_and_resume_use_public_methods():
    risk = RiskManager(Ledger(initial_cash="100"))
    risk.kill("operator")
    assert risk.is_killed is True
    assert risk.kill_reason == "operator"
    risk.resume()
    assert risk.is_killed is False


def test_kill_state_survives_restart(tmp_path):
    path = tmp_path / "risk.db"
    ledger = Ledger(str(path), initial_cash="100")
    risk = RiskManager(ledger)
    risk.kill("operator")
    ledger.close()

    reopened = Ledger(str(path), initial_cash="100")
    restored = RiskManager(reopened)
    assert restored.is_killed is True
    assert restored.kill_reason == "operator"
    restored.resume()
    reopened.close()

    reopened_again = Ledger(str(path), initial_cash="100")
    assert RiskManager(reopened_again).is_killed is False


def test_peak_equity_survives_restart_for_drawdown_control(tmp_path):
    path = tmp_path / "risk.db"
    ledger = Ledger(str(path), initial_cash="100")
    ledger.record_fill(fill())
    risk = RiskManager(ledger, max_drawdown_pct="0.10")
    assert risk.evaluate({"yes": Decimal("0.7")}) is False
    assert risk.stats["peak_equity"] == "120.0"
    ledger.close()

    reopened = Ledger(str(path), initial_cash="100")
    restored = RiskManager(reopened, max_drawdown_pct="0.10")
    assert restored.evaluate({"yes": Decimal("0.5")}) is True
    assert restored.stats["peak_equity"] == "120.0"


def test_allocation_is_capped_by_equity_and_cash():
    ledger = Ledger(initial_cash="100")
    risk = RiskManager(ledger, max_position_pct="0.05")
    assert risk.can_allocate(Decimal("5"), {}) is True
    assert risk.can_allocate(Decimal("5.01"), {}) is False
