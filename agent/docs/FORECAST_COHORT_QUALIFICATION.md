# Forecast Cohort Qualification

Poly-Shadow evaluates forecasters as a pre-registered research cohort before any forecast can support a paper-trading proposal.

This milestone does **not** grant trading authority. The strongest possible automated status is:

```text
ELIGIBLE_FOR_PAPER_PROPOSAL
```

That status means the evidence is strong enough to justify a separate human-reviewed paper-strategy proposal. It never connects forecasting to `PaperBroker`, `RiskManager`, position sizing, or live execution.

## Why a cohort is pre-registered

A forecaster must not be selected, filtered, retried, or given new thresholds after its outcomes are known. A qualification manifest therefore freezes:

- cohort ID and UTC start time;
- exact provider/model set;
- semantic SHA-256 of the provider configuration;
- semantic SHA-256 of the evidence manifest;
- SHA-256 of the qualification-policy parameters;
- SHA-256 of the forecast system prompt plus request-template protocol version;
- a dedicated SQLite forecasting journal;
- a fixed decision sample of 120 unique conditions;
- a maximum scheduled forecast horizon of 90 days.

The manifest itself has a deterministic SHA-256 digest. JSON whitespace and key ordering do not affect the provider/evidence semantic hashes. Existing cohort manifests should not be overwritten. Any change to the forecasters, evidence-source selection, prompt protocol, policy, or decision protocol requires a new cohort.

Create a cohort manifest from the exact provider and evidence configurations that will be used for collection:

```bash
cd agent
python scripts/init_forecast_cohort.py \
  --cohort-id fq-v1-2026-08-22 \
  --providers providers.json \
  --evidence evidence.json \
  --output cohorts/fq-v1-2026-08-22.json
```

## Dedicated journal and frozen configuration

Qualification cohorts must use a database that is not the ordinary mixed research journal. This makes every successfully issued request after cohort start part of the cohort denominator and lets missing provider results remain visible instead of disappearing.

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

- provider/model drift;
- any semantic change to `providers.json`;
- any semantic change to `evidence.json`;
- a changed qualification-policy hash;
- a changed forecast-protocol hash;
- collection before the preregistered start time;
- use of the default mixed forecasting journal;
- requests already present before cohort start;
- `--allow-market-metadata-only`.

Qualification collection considers only unseen conditions whose scheduled resolution time is no more than 90 days after collection. Once 120 unique conditions have been issued into the cohort journal, the collector returns `COHORT_TARGET_FULL` and will not add another condition.

The collector also excludes already-seen conditions before invoking any model. A provider failure therefore consumes that condition's one canonical attempt; rerunning collection cannot retry the same condition for a better score.

## Canonical qualification sample

For each preregistered forecaster, the official sample uses the **first request for each unique Polymarket condition ID** after cohort start. The cohort contains at most 120 unique conditions.

Later manually inserted forecasts on the same condition are counted as repeat attempts and excluded from eligibility calculations. A journal containing more than 120 unique conditions is `INVALID`.

Each canonical condition attempt can resolve as one of four operational outcomes:

1. **scored** — non-abstaining forecast plus contemporaneous market baseline;
2. **abstention** — provider explicitly abstained;
3. **provider failure** — provider invocation failed and the failure was journaled;
4. **incomplete** — the request exists but no forecast or provider-failure record exists.

Coverage is:

```text
scored resolved conditions / all canonical resolved conditions
```

Abstentions, provider failures, and incomplete attempts reduce usable coverage instead of silently disappearing.

## One decision, not repeated peeking

`cohort_report.py --watch` may be run continuously, but intermediate reports are descriptive only. `PS-FQ-1` does not make a performance decision until all **120** canonical conditions have authoritative resolutions.

This avoids treating repeated views of an ordinary fixed-sample 95% confidence interval as repeated opportunities to pass. Once all 120 conditions are resolved, the cohort receives one terminal decision:

- all evidence/diversity and performance gates pass → `ELIGIBLE_FOR_PAPER_PROPOSAL`;
- any fixed gate fails → `NOT_QUALIFIED`.

A failed cohort is not extended with more conditions. A new experiment requires a new preregistered cohort.

## Fixed policy `PS-FQ-1`

The first qualification policy is deliberately conservative and code-defined rather than CLI-tunable:

| Gate | Requirement |
|---|---:|
| Fixed decision sample | exactly 120 unique conditions |
| Authoritative resolutions before decision | 120 / 120 |
| Resolved Polymarket event clusters | >= 60 |
| Scored conditions | >= 96 |
| Coverage | >= 0.80 |
| Mean Brier skill vs market | > 0 |
| 95% event-cluster-bootstrap Brier-skill lower bound | > 0 |
| Expected calibration error | <= 0.10 |
| Category diversity | >= 3 categories with >= 10 scored each |
| Horizon diversity | >= 2 horizon buckets with >= 10 scored each |
| Material slice regression | no eligible category/horizon slice below -0.02 mean Brier skill |
| Scheduled collection horizon | <= 90 days |

Brier skill is defined as:

```text
market Brier score - forecaster Brier score
```

Positive values mean the forecaster beat the contemporaneous Polymarket probability on that resolved condition.

Changing these thresholds without changing the policy hash invalidates an existing manifest. A deliberate future policy revision should receive a new policy ID and a new cohort.

## Confidence interval and dependence control

The confidence interval is a deterministic percentile bootstrap over **Polymarket event clusters**, not individual forecast rows. Conditions sharing the same frozen Gamma `event_id` are resampled together. This reduces false precision from related markets belonging to one event.

If an event ID is unavailable, all such missing-event observations share one conservative unknown-event cluster rather than being treated as independent.

The bootstrap is reproducible from the policy ID, forecaster key, metric name, and fixed hashing procedure. It remains a research diagnostic rather than a guarantee that prediction-market event clusters are perfectly independent or identically distributed. The fixed single-decision sample prevents continuous monitoring from turning that ordinary interval into a sequential test.

## Category and horizon slices

Category comes from the frozen `Polymarket Gamma market metadata` evidence captured before forecast issuance.

Horizon is derived from the frozen request timestamps:

- `<=1d`
- `1-7d`
- `7-30d`
- `30-90d`

Conditions scheduled beyond 90 days are not admitted to the qualification cohort. Unknown or invalid horizon/category values remain visible but do not satisfy diversity gates.

## Resolution and monitoring loop

Use the existing authoritative-resolution watcher against the cohort database:

```bash
python scripts/capture_resolutions.py \
  --db data/cohorts/fq-v1-2026-08-22.db \
  --watch \
  --interval-seconds 300
```

Monitor cohort progress in another process:

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
- resolved event-cluster count;
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
: The fixed 120-condition sample is still being issued or awaiting resolution. Intermediate performance numbers are descriptive only.

`NOT_QUALIFIED`
: All 120 conditions have resolved, but one or more fixed evidence, diversity, coverage, calibration, confidence, skill, or slice gates failed.

`INVALID`
: The cohort contract was violated or contradictory journal state was observed—for example, more than 120 unique conditions or both a forecast and provider failure for the same request/provider/model.

`ELIGIBLE_FOR_PAPER_PROPOSAL`
: All 120 conditions resolved and every `PS-FQ-1` gate passed. This is only permission to draft a separate bounded paper-strategy proposal.

## Execution boundary

Cohort qualification is research-only. The evaluation package is covered by the same structural import test as forecasting: neither may import the paper broker, risk manager, execution path, or order-placement code.
