# Forecast Resolution Capture

Poly-Shadow can mature previously issued research forecasts without giving forecasting any execution authority.

## Authoritative source

Resolution capture reads the public Polymarket CLOB market endpoint for each unresolved forecast condition:

```text
GET {POLYMARKET_CLOB_URL}/markets/{condition_id}
```

A binary forecast condition is considered resolved only when all of the following are true:

1. the returned `condition_id` exactly matches the journaled condition;
2. `closed` is exactly `true`;
3. the response contains exactly two token records;
4. their normalized outcomes are exactly `Yes` and `No`;
5. exactly one token has `winner=true`.

Poly-Shadow never infers the outcome from token price, midpoint, last trade, Gamma `outcomePrices`, or model output.

## One-shot capture

```bash
cd agent
python scripts/capture_resolutions.py --db data/forecasting.db
```

The command selects the oldest distinct condition IDs that exist in the forecast-request journal but not in the resolution table. Each condition is checked independently. Successful resolutions are appended to the same research journal and become visible immediately to `scripts/forecast_report.py` through the existing `resolved_forecasts()` query.

Open markets are ordinary unresolved results, not failures. HTTP/schema/identity failures are isolated per condition and produce a non-zero one-shot exit code without discarding successful captures from the same batch.

## Watch mode

```bash
cd agent
python scripts/capture_resolutions.py \
  --db data/forecasting.db \
  --watch \
  --interval-seconds 300
```

Watch intervals below 60 seconds are rejected. The watcher only revisits conditions with no recorded resolution, so an outcome that has already been captured is not repeatedly polled after restart.

Useful bounds:

```text
--limit 100
--concurrency 8
--interval-seconds 300
```

## Timestamp semantics

The existing forecast-journal column is named `resolved_at`. When resolution arrives through this polling/catch-up path, its value is the first UTC timestamp at which Poly-Shadow observed authoritative resolved CLOB state.

It is deliberately **not** presented as the exact on-chain or WebSocket resolution-event timestamp, because the current CLOB market snapshot does not provide that event time. The deterministic resolution identity is instead derived from:

```text
Polymarket CLOB + condition_id + winning_token_id
```

This is sufficient for idempotent maturation and outcome scoring without inventing unavailable temporal precision. A future event-stream enhancement may preserve the exact `market_resolved` event timestamp separately.

## Scoring path

Once a resolution is recorded:

```text
frozen forecast request
  + frozen forecast probability
  + contemporaneous market baseline
  + authoritative binary outcome
        ↓
resolved_forecasts()
        ↓
Brier score / log loss / calibration
        ↓
comparison against market baseline
```

No ensemble weight is earned merely because a market has resolved. Skill still requires resolved out-of-sample performance versus the contemporaneous market baseline.

## Execution boundary

Resolution capture is research-only. It does not import or call `PaperBroker`, `RiskManager`, directional sizing, or a CLOB order client. It uses public market reads only and cannot create paper or live orders.
