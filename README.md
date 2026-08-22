# PolyMarket-Shadow

Poly-Shadow is a **paper-only Polymarket observation, simulation, accounting, and strategy-evaluation system** with a Flutter monitoring client.

The v0.1 prototype treated AI consensus and nominal market prices too directly as trading inputs. v0.2 rebuilt the market/execution core around truthful identity, executable depth, fees, durable accounting, resolution, and risk. v0.3 begins the next layer: calibrated forecasting research that must demonstrate value against the market baseline before it can influence paper execution.

## Current status

- **Live-capital execution: absent.** `PAPER_TRADING=false` is rejected at runtime.
- **Canonical trading state:** SQLite append-only ledger, not CSV.
- **Market data:** Gamma discovery + token-ID market WebSocket adapter.
- **Execution:** depth-aware paper fills only.
- **Structural arbitrage:** equal-share YES/NO pairs evaluated after executable depth, fees, and configured slippage reserve.
- **Risk:** ledger-backed equity/drawdown controls.
- **Resolution:** idempotent stream-driven settlement.
- **API:** loopback-only by default (`127.0.0.1`).
- **Forecasting research:** explicit probabilities, uncertainty, timestamped market baselines, evidence provenance, proper scoring, calibration, and skill-weighted ensembles.
- **Forecast/execution boundary:** forecasting has no broker or risk-manager dependency and cannot create paper orders.
- **Flutter:** existing dashboard source is preserved but is not yet requalified against the v0.2 API.

## Structure

```text
PolyMarket-Shadow/
├── agent/      # Python truthful paper core + forecasting research + API
└── flutter/    # Flutter dashboard; P1 requalification pending
```

## Agent quickstart

```bash
cd agent
cp .env.example .env
python -m pip install -r requirements.txt
python src/main.py
```

Local API: `http://127.0.0.1:8000/api`

No Polymarket trading credentials are required by the paper core.

## Verification

```bash
cd agent
pytest -v
ruff check src/
pylint src/ --disable=C0114,C0115,C0116 --fail-under=7.0
```

The deterministic suite includes captured Polymarket fixtures plus forecasting tests for anti-leakage timestamps, evidence hashes, market baselines, provider isolation, append-only journaling, proper scoring, calibration, and out-of-sample skill weighting.

## Promotion boundary

The system is intended to **measure strategies, not authorize capital**. Forecasts must be evaluated on resolved markets against the contemporaneous market-implied baseline. Model agreement is not a probability and does not unlock Kelly sizing or directional paper trading.

Live execution would require a separate design, explicit approval, authentication/secret handling, execution reconciliation, additional failure testing, and an evidence-based promotion decision.

See `agent/README.md` for the backend architecture and research contract.
