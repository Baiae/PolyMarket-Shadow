from adapters.polymarket.gamma import GammaAdapter


def test_gamma_market_requires_explicit_trade_ready_flags():
    ready = {
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "enableOrderBook": True,
    }
    assert GammaAdapter.is_trade_ready(ready) is True

    for key in ("active", "acceptingOrders", "enableOrderBook"):
        candidate = dict(ready)
        candidate[key] = False
        assert GammaAdapter.is_trade_ready(candidate) is False

    closed = dict(ready)
    closed["closed"] = True
    assert GammaAdapter.is_trade_ready(closed) is False

    missing_flag = dict(ready)
    missing_flag.pop("acceptingOrders")
    assert GammaAdapter.is_trade_ready(missing_flag) is False
