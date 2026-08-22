# PolyMarket-Shadow

Poly-Shadow v0.2 is a **paper-only Polymarket observation, simulation, accounting, and strategy-evaluation system** with a Flutter monitoring client.

The v0.1 prototype treated AI consensus and nominal market prices too directly as trading inputs. v0.2 deliberately reverses that priority: market identity, executable order-book depth, fees, durable accounting, resolution, and risk must be trustworthy before any forecasting system can earn a role in execution.

## Current status

- **Live-capital execution: absent.** `PAPER_TRADING=false` is rejected at runtime.
- **Canonical state:** SQLite append-only ledger, not CSV.
- **Market data:** Gamma discovery + token-ID market WebSocket adapter.
- **Execution:** depth-aware paper fills only.
- **Structural arbitrage:** equal-share YES/NO pairs evaluated after executable depth, fees, and configured slippage reserve.
- **Risk:** ledger-backed equity/drawdown controls.
- **Resolution:** idempotent stream-driven settlement.
- **API:** loopback-only by default (`127.0.0.1`).
- **LLM swarm:** retained only as legacy/P1 research code and disconnected from the v0.2 trading path.
- **Flutter:** existing dashboard source is preserved but is not yet requalified against the v0.2 API.

## Structure

```text
PolyMarket-Shadow/
├── agent/      # Python v0.2 truthful paper core + API
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

No Polymarket trading credentials are required by the v0.2 paper core.

## Verification

```bash
cd agent
pytest -v
ruff check src/
pylint src/ --disable=C0114,C0115,C0116 --fail-under=7.0
```

The deterministic test suite includes captured/documented Polymarket-shaped fixtures for market identity, book updates, depth walking, fees, atomic binary-paper execution, ledger invariants, resolution idempotency, risk, and orchestrator replay.

## Promotion boundary

v0.2 is intended to **measure strategies, not authorize capital**. Live execution would require a separate design, explicit approval, authentication/secret handling, execution reconciliation, additional failure testing, and an evidence-based promotion decision.

See `agent/README.md` for the backend architecture and API contract.
