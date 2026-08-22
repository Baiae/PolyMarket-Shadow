# Forecast Cohort Qualification

Poly-Shadow evaluates forecasters as a pre-registered research cohort before any forecast can support a paper-trading proposal.

This milestone does **not** grant trading authority. The strongest possible automated status is:

```text
ELIGIBLE_FOR_PAPER_PROPOSAL
```

That status means the evidence is strong enough to justify a separate human-reviewed paper-strategy proposal. It never connects forecasting to `PaperBroker`, `RiskManager`, position sizing, or live execution.

## Why a cohort is pre-registered

A forecaster must not be selected, filtered, retried, or given new thresholds after its outcomes are known. A cohort manifest therefore freezes:

- cohort ID;
- policy ID;
- UTC start time;
- exact provider/model set;
- the requirement to use a dedicated SQLite forecasting journal.

The manifest has a deterministic SHA-256 digest. Existing manifests should not be overwritten. Start a new cohort if the provider set or qualification policy changes.

Create a cohort manifest from the same provider configuration that will be used for collection:

```bash
cd agent
python scripts/init_forecast_cohort.py \
  --cohort-id fq-v1-2026-08-22 \
  --providers providers.json \
  --output cohorts/fq-v1-2026-08-22.json
```

## Dedicated journal rule

Qualification cohorts must use a database that is not the ordinary mixed research journal. This makes every request after the cohort start time part of the cohort opportunity set and lets missing provider results remain visible instead of disappearing from the denominator.

Example:

```bash
python scripts/collect_forecasts.py \
  --cohort cohorts/fq-v1-2026-08-22.json \
  --providers providers.json \
  --evidence evidence.json \
  --db data/cohorts/fq-v1-2026-08-22.db \
  --sample-count 3
```

When `--cohort` is supplied, collection rejects:

- a provider/model configuration that differs from preregistration;
- an unsupported policy ID;
- collection before the preregistered start time;
- use of the default mixed forecasting journal.

Independent evidence remains required for skill claims. `--allow-market-metadata-only` remains a harness/debug escape hatch, not a qualification mode.

## Canonical qualification sample

For each preregistered forecaster, the official qualification sample uses the **first request for each unique Polymarket condition ID** after cohort start.

Later forecasts on the same condition are counted as repeat attempts and excluded from eligibility calculations. This prevents retries, prompt changes, or repeated sampling of the same eventual outcome from manufacturing a better score.

Each canonical condition attempt can resolve as one of four operational outcomes:

1. **scored** — non-abstaining forecast plus contemporaneous market baseline;
2. **abstention** — provider explicitly abstained;
3. **provider failure** — provider invocation failed and the failure was journaled;
4. **incomplete** — the request exists but no forecast or provider-failure record exists.

Coverage is:

```text
scored resolved conditions / all canonical resolved conditions
```

Abstentions, provider failures, and incomplete attempts therefore reduce usable coverage instead of silently disappearing.

## Fixed policy `PS-FQ-1`

The first qualification policy is deliberately conservative and is encoded in source, not supplied through CLI flags:

| Gate | Requirement |
|---|---:|
| Unique resolved conditions | >= 100 |
| Resolved event clusters | >= 50 |
| Scored conditions | >= 80 |
| Coverage | >= 0.80 |
| Mean Brier skill vs market | > 0 |
| 95% Brier-skill lower confidence bound | > 0 |
| Expected calibration error | <= 0.10 |
| Category diversity | >= 3 categories with >= 10 scored each |
| Horizon diversity | >= 2 horizon buckets with >= 10 scored each |
| Material slice regression | no eligible category/horizon slice below -0.02 mean Brier skill |

Brier skill is defined as:

```text
market Brier score - forecaster Brier score
```

Positive values mean the forecaster beat the contemporaneous Polymarket probability on that resolved condition.

Changing these thresholds requires a new policy ID and a new cohort. They should not be tuned against results already collected under `PS-FQ-1`.

## Confidence interval and dependence control

The confidence interval is a deterministic percentile bootstrap over **Polymarket event clusters**, not individual forecast rows. Conditions sharing the same frozen Gamma `event_id` are resampled together. This reduces false precision from related markets belonging to one event.

If an event ID is unavailable, all such missing-event observations share one conservative unknown-event cluster rather than being treated as independent.

The bootstrap is reproducible from the policy ID, forecaster key, metric name, and fixed hashing procedure. It is still a research diagnostic, not a guarantee that prediction-market observations are fully independent or identically distributed.

## Category and horizon slices

Category comes from the frozen `Polymarket Gamma market metadata` evidence captured before forecast issuance.

Horizon is derived from the frozen request timestamps:

- `<=1d`
- `1-7d`
- `7-30d`
- `30-90d`
- `>90d`

Unknown or invalid horizon/category values remain visible but do not satisfy diversity gates.

## Resolution and monitoring loop

Use the existing authoritative-resolution watcher against the cohort database:

```bash
python scripts/capture_resolutions.py \
  --db data/cohorts/fq-v1-2026-08-22.db \
  --watch \
  --interval-seconds 300
```

Monitor cohort evidence in another process:

```bash
python scripts/cohort_report.py \
  --cohort cohorts/fq-v1-2026-08-22.json \
  --db data/cohorts/fq-v1-2026-08-22.db \
  --output data/cohorts/fq-v1-2026-08-22-report.json \
  --watch \
  --interval-seconds 300
```

The report includes, per forecaster:

- total, resolved, and unresolved canonical conditions;
- event-cluster count;
- repeat attempts excluded;
- scored, abstention, provider-failure, and incomplete counts;
- coverage;
- mean Brier and log loss against the market;
- event-cluster bootstrap skill intervals;
- expected calibration error;
- category and horizon slices;
- every fixed policy gate and its current state.

## Status meanings

`COLLECTING`
: The cohort has not yet accumulated the pre-registered minimum evidence/diversity required for a decision.

`NOT_QUALIFIED`
: The evidence minimum has been reached, but one or more performance, coverage, calibration, confidence, or slice gates failed.

`INVALID`
: Contradictory journal state was observed, such as both a forecast and provider failure for the same request/provider/model.

`ELIGIBLE_FOR_PAPER_PROPOSAL`
: Every `PS-FQ-1` gate passed. This is only permission to draft a separate bounded paper-strategy proposal.

## Execution boundary

Cohort qualification is research-only. The evaluation package is covered by the same structural import test as forecasting: neither may import the paper broker, risk manager, execution path, or order-placement code.
