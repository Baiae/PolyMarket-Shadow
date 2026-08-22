# Poly-Shadow — Truthful Paper Core + Forecast Research

> **Paper simulation only.** There is no live-order adapter, and setting `PAPER_TRADING=false` aborts startup.

## Purpose

The paper core makes the observation-to-accounting chain trustworthy before forecasting can influence execution:

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

The P1 forecasting subsystem is deliberately separate:

```text
Timestamped market baseline
  + timestamped evidence provenance
  → provider-neutral probability forecast
  → append-only forecast journal
  → resolution
  → Brier / log loss / calibration
  → comparison with market baseline
  → evidence-based ensemble weight
```

A downstream component must not manufacture information omitted upstream. Midpoint/display prices are not executable fills, and model vote fractions are not calibrated event probabilities.

## Paper-core architecture

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
          ↓
PaperBroker
  └── atomic YES + NO fills
          ↓
Ledger (SQLite)
          ↓
RiskManager
          ↓
FastAPI local control/observation API
```

## Forecasting research contract

`src/forecasting/` and `src/evaluation/` provide:

- `ForecastRequest`: one market/question at one issuance time;
- `EvidenceItem`: source, retrieval/publication timestamps, immutable content hash, and content;
- `MarketBaseline`: contemporaneous YES midpoint with timestamp/source/bid/ask;
- `ProbabilisticForecast`: explicit `probability_yes`, uncertainty, abstention, model identity, and provenance links;
- `OpenAICompatibleForecastProvider`: local or remote OpenAI-compatible adapter with no fixed model roster;
- `ForecastExperiment`: bounded multi-provider research runner with failure isolation;
- `ForecastJournal`: append-only SQLite requests/evidence/forecasts/resolutions;
- Brier score, log loss, reliability bins, expected calibration error, and market-baseline comparisons;
- skill-weighted ensembles whose weights must come from measured Brier skill.

### Anti-leakage rules

A request is rejected if evidence or the market baseline is timestamped after forecast issuance. Forecasts issued at or after a known resolution time are rejected. The provider prompt hides the market baseline by default to avoid price anchoring; exposing it is an explicit experiment flag.

### Execution boundary

The forecasting runner imports neither `PaperBroker` nor `RiskManager`. Forecasting output is research evidence only. There is no directional execution path and no Kelly sizing input based on model output.

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
- Trading state defaults to `data/poly_shadow.db` and survives restart.
- Forecast research state defaults to `data/forecasting.db` and is separate from the trading ledger.
- Books without timestamps, stale books, missing marks, insufficient depth, insufficient paper cash, duplicate fill IDs, and non-positive net arbitrage are fail-closed conditions.
- Binary arbitrage records both legs in one SQLite transaction.
- A resolution can settle a trading condition only once.
- The API adds no wildcard CORS policy. Remote control is not enabled by default.

## Configuration

| Setting | Default | Purpose |
|---|---:|---|
| `PAPER_TRADING` | `true` | Must remain true |
| `INITIAL_BANKROLL` | `1000` | Initial paper cash |
| `DATABASE_PATH` | `data/poly_shadow.db` | Canonical trading state |
| `FORECAST_DATABASE_PATH` | `data/forecasting.db` | Append-only forecasting research journal |
| `MARKET_DISCOVERY_LIMIT` | `50` | Gamma markets loaded at startup |
| `MARKET_MAX_BOOK_AGE_MS` | `60000` | Stale-book rejection threshold |
| `ARB_MIN_NET_PROFIT` | `0.01` | Minimum net paper arb profit |
| `ARB_MAX_SHARES` | `50` | Maximum shares evaluated per opportunity |
| `ARB_SLIPPAGE_RESERVE_PER_SHARE` | `0` | Conservative extra cost reserve |
| `MAX_DRAWDOWN_PCT` | `0.30` | Paper kill-switch threshold |
| `MAX_POSITION_PCT` | `0.05` | Allocation cap as fraction of equity |
| `API_HOST` | `127.0.0.1` | Local API binding |
| `CONTROL_TOKEN` | empty | Optional additional local control token |

Provider credentials/endpoints are supplied to forecasting research runners, not to the paper execution process.

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

## Forecast evaluation

After resolutions have been recorded in the forecast journal:

```bash
cd agent
python scripts/forecast_report.py --db data/forecasting.db
```

The report exposes mean Brier/log loss alongside the corresponding market-baseline scores. A forecaster is not considered useful merely because it sounds confident or agrees with other models.

## Verification

```bash
pytest -v
ruff check src/
pylint src/ --disable=C0114,C0115,C0116 --fail-under=7.0
```

The deterministic suite remains offline. The separate bounded live Gamma/WebSocket workflow verifies external market-data compatibility.

## Remaining P1 work

- accumulate resolved out-of-sample forecasting evidence;
- evaluate whale-flow features as hypotheses rather than automatic signals;
- migrate/requalify the Flutter dashboard;
- lock dependencies and upgrade package families deliberately;
- authenticated non-loopback operator access, if ever needed.

## Live-capital boundary

There is no CLOB order client in the runtime dependency path. Live capital is not unlocked by an environment variable. Any future live-execution capability requires a separate proposal, explicit approval, reconciliation/idempotency design, authentication and secrets review, failure testing, capital limits, and evidence from resolved paper evaluation.
