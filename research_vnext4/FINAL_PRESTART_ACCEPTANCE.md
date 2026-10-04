# BTC Predictive vNext4 — final pre-start acceptance after independent REWORK

Date: 2026-10-04.
Scope: engineering/prospective integrity and audit-driven predictive research.
This is not evidence of future predictive quality and grants no trading authority.

## Independent-audit defects

### Critical: false admission from overlapping forecasts — CLOSED
- Admission statistics are computed only on fixed-phase non-overlapping windows.
- Brier, Log Loss, calibration and 14/28-day block bootstrap use that same subset.
- Overlapping forecasts are descriptive only.
- Adversarial regression reproducing thousands of overlapping wins with losses on
  every independent 72h window now returns no admission.

### Critical: executable contamination via mutable evidence checkout — CLOSED
- Evidence checkout is ledger/raw storage only.
- Executable runtime is extracted from immutable source commit
  4447bd1a82f68b281a3fafb2b76aae238b0c5335.
- Runtime is executed under python -I.
- Deliberately injected sitecustomize.py in the mutable checkout does not execute.
- Forecast and outcome both verify the signed pre-start manifest.

### Baseline-seed reproducibility — CLOSED
- Exact raw Binance candles used to construct the pre-start adaptive seed are
  frozen as deterministic gzip sources.
- Selftest recomputes labels and seed records from those sources and requires exact
  equality with the artifact.
- Hourly seed source SHA256:
  e6dba53ba2a5c4abe36ecb0485d76080faf298ab58d13926450ef05c3ac86c29
- 15m seed source SHA256:
  ec45205beceaa7d5b6971060e3d76525fc774ac6fb9e52f512e9a911fe2081d4

### Volatility episode independence — CLOSED
- Episode/admission coverage is evaluated on the fixed-phase non-overlapping
  sequence rather than on every overlapping bin switch.

### Early-warning uncertainty — CLOSED FOR MEASUREMENT
- Frozen calibration-only thresholds remain unchanged.
- Prospective reporting separates overlapping descriptive output from fixed-phase
  non-overlap inference.
- Recall/FPR/precision use uncertainty intervals in the frozen scorecard.
- Audit-driven historical diagnostics additionally expose miss rate, false-alert
  share, alerts per 100 anchors and time-to-touch.

## Verification receipts

- vNext4 source smoke: GitHub Actions run 37207232460 — SUCCESS.
- vNext4 independent pre-start audit: run 37207373424 — SUCCESS after rerun.
- Frozen late-period diagnostic with paired block uncertainty: run 37208921627 — SUCCESS.
- Feature-family ablation with paired block uncertainty: run 37208821374 — SUCCESS.
- Generalized fixed-barrier first-passage research: run 37208404193 — SUCCESS.

The older combined research workflow had publication conflicts and was retired.
Its failures are not model/test failures; the dedicated workflows above completed
successfully.

## Predictive-research decision

1. Exact frozen 15m artifacts are encouraging on inspected late history: all three
   beat the causal vol90d baseline on fixed-phase non-overlap observations with
   positive paired 14/28-day block intervals. This is diagnostic, not prospective.
2. The hourly 72h head has too few independent late-period observations; its paired
   gain intervals cross zero.
3. Feature-family ablation finds no removal supported by paired block uncertainty
   across the inspected folds. No feature deletion is promoted.
4. A generalized model for fixed barriers is regime-unstable: it wins in 2025Q3,
   loses in 2025Q4 and is approximately neutral in 2026H1. No fixed-price
   probability head is promoted.

## Final pre-start status

- Engineering/prospective integrity: ACCEPT for shadow collection.
- Predictive acceptance: FALSE.
- Trading authority: FALSE.
- Frozen contenders: logistic, GBDT, competing-risks.
- Operational fixed-price endpoints remain outcome-only.
- vNext3 is non-admissible and retired.
- vNext4 remains numerically unchanged after registration; changing it now from
  inspected diagnostics would introduce selection bias.

The next admissible evidence is future vNext4 data after the registered start
2026-10-05 00:00 UTC (03:00 MSK).
