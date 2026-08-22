# Poly-Shadow v0.2 — Truthful Paper Core

> **Paper simulation only.** There is no live-order adapter in v0.2, and setting `PAPER_TRADING=false` aborts startup.

## Purpose

v0.2 makes the observation-to-accounting chain trustworthy before adding forecasting ambition. The core invariant is:

```text
Market identity
  → token-specific order books
  → executable cost
  → paper fills
  → durable ledger
  → equity/risk
  → resolution
  → evaluation
```

A downstream component must not manufacture information omitted upstream. In particular, midpoint/display prices are not treated as executable fills, and an ensemble vote count is not treated as a calibrated event probability.

## Architecture

```text
GammaAdapter
  └── MarketIdentity
      ├── Gamma market ID
      ├── condition ID
      ├── YES CLOB token ID
      └── NO CLOB token ID

PolymarketStream
  ├── book
  ├── price_change
  ├── last_trade_price
  ├── best_bid_ask
  └── market_resolved
          ↓
OrderBook (Decimal)
          ↓
ExecutableArbitrageDetector
  ├── equal-share depth
  ├── fee curve
  └── optional slippage reserve
          ↓
PaperBroker
  └── atomic YES + NO fills
          ↓
Ledger (SQLite)
  ├── immutable fill entries
  ├── reservations
  ├── positions
  └── idempotent settlement
          ↓
RiskManager
  ├── equity
  ├── peak equity
  ├── drawdown kill
  └── allocation/rate limits
          ↓
FastAPI local control/observation API
```

## Quickstart

```bash
cd agent
cp .env.example .env
python -m pip install -r requirements.txt
python src/main.py
```

The API binds to `127.0.0.1:8000` by default.

### Important runtime properties

- Public market-data APIs are used for the paper core; no Polymarket private trading keys are required.
- SQLite state defaults to `data/poly_shadow.db` and survives restart.
- `logs/` and the database parent directory are created automatically.
- Books without timestamps, stale books, missing marks, insufficient depth, insufficient paper cash, duplicate fill IDs, and non-positive net arbitrage are fail-closed conditions.
- Binary arbitrage records both legs in one SQLite transaction. One paper leg cannot commit without the other.
- A resolution can settle a condition only once.
- The API adds no wildcard CORS policy. Remote control is not enabled by default.

## Configuration

See `.env.example`. The principal P0 settings are:

| Setting | Default | Purpose |
|---|---:|---|
| `PAPER_TRADING` | `true` | Must remain true in v0.2 |
| `INITIAL_BANKROLL` | `1000` | Initial paper cash |
| `DATABASE_PATH` | `data/poly_shadow.db` | Canonical durable state |
| `MARKET_DISCOVERY_LIMIT` | `50` | Gamma markets loaded at startup |
| `MARKET_MAX_BOOK_AGE_MS` | `60000` | Stale-book rejection threshold |
| `ARB_MIN_NET_PROFIT` | `0.01` | Minimum net paper arb profit |
| `ARB_MAX_SHARES` | `50` | Maximum shares evaluated per opportunity |
| `ARB_SLIPPAGE_RESERVE_PER_SHARE` | `0` | Conservative extra cost reserve |
| `MAX_DRAWDOWN_PCT` | `0.30` | Paper kill-switch threshold |
| `MAX_POSITION_PCT` | `0.05` | Allocation cap as fraction of equity |
| `API_HOST` | `127.0.0.1` | Local API binding |
| `CONTROL_TOKEN` | empty | Optional additional local control token |

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/healthz` | Process/feed health and last runtime error |
| GET | `/api/status` | Paper mode, tracked markets/books, positions, risk stats |
| GET | `/api/trades` | Recent normalized last-trade events |
| GET | `/api/signals` | Executable structural-arbitrage observations |
| GET | `/api/positions` | Open ledger-derived paper positions |
| POST | `/api/kill` | Stop new paper order generation; local-only |
| POST | `/api/resume` | Resume paper order generation; local-only |

If `CONTROL_TOKEN` is set, control requests must also send it in `X-Poly-Shadow-Control-Token`.

## Verification

```bash
pytest -v
ruff check src/
pylint src/ --disable=C0114,C0115,C0116 --fail-under=7.0
```

The suite is intentionally offline for deterministic contract tests. A bounded live Gamma/WebSocket smoke check remains a separate requalification step because external API availability should not determine unit-test results.

## Deferred to P1

- calibrated probabilistic forecasting and proper scoring rules;
- evidence provenance for forecasts;
- provider-neutral local/remote model adapters;
- whale-flow evaluation as a hypothesis rather than an automatic signal;
- Flutter API migration/requalification;
- dependency locking and deliberate package-family upgrades;
- authenticated non-loopback operator access, if ever needed.

`src/strategy/swarm.py` remains only to preserve the v0.1 experiment/tests while that P1 redesign is pending. It is not imported by `main.py` and cannot produce v0.2 paper orders.

## Live-capital boundary

There is no CLOB order client in the v0.2 runtime dependency path. Live capital is not unlocked by an environment variable. Any future live-execution capability requires a separate proposal, explicit approval, reconciliation/idempotency design, authentication and secrets review, failure testing, capital limits, and evidence from resolved paper evaluation.
