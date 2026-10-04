# BTC Predictive vNext4 — remediation of independent vNext3 REWORK

vNext4 exists because the independent audit demonstrated two critical defects in
vNext3. vNext3 must not be used as admissible prospective evidence.

## Critical defect 1 — false admission from overlapping forecasts

vNext3 counted non-overlapping windows but evaluated Brier, Log Loss and bootstrap
gain on the overlapping sample. vNext4 changes the admission scope to
`FIXED_PHASE_NONOVERLAP_ONLY`.

For every contender:
- Brier used for admission is computed only on fixed-phase non-overlapping windows.
- Log Loss used for admission is computed only on the same windows.
- Calibration/ECE admission is computed only on the same windows.
- 14-day and 28-day block-bootstrap lower bounds are computed only from those
  non-overlapping windows.
- Overlapping forecasts remain descriptive only.
- A regression test reconstructs the audit's adversarial situation: thousands of
  overlapping wins cannot overcome losses on every independent 72h window.

## Critical defect 2 — executable source contamination

The mutable evidence branch is no longer an executable source.

Production workflow:
1. checks out the evidence branch only for the ledger/raw evidence;
2. creates a clean runtime directory from one immutable Git source commit;
3. executes that runtime with `python -I`;
4. passes the evidence checkout separately via `BTC_VNEXT4_EVIDENCE_ROOT`;
5. verifies the signed pre-start manifest before forecast and outcome.

The manifest binds the immutable source SHA, every runtime source/artifact/protocol
hash, the raw adaptive-baseline seed source and both workflow hashes.

## Baseline-seed reproducibility

The exact Binance candles used to create the pre-start vol90d baseline seed are
stored as deterministic gzip files. Their compressed and logical SHA256 values are
embedded in the frozen artifact. Selftest independently reconstructs every seed
record and requires exact equality.

## Volatility episodes

Admission no longer increments an episode counter on every overlapping bin switch.
Episodes are counted only on the already non-overlapping fixed-phase sequence.
Each observation in that sequence is separated by a full target horizon.

## Early warning

Calibration-period FPR=20% thresholds remain frozen pre-start. Future recall, FPR
and precision are reported separately by volatility bin with 95% Wilson intervals.
The fixed-phase non-overlapping report is inferential; overlapping output is
explicitly descriptive. Median time from a true alert to first touch is also
reported.

## Fixed price questions

The 82,500/87,000 (72h) and 81,500/88,000 (168h) questions remain separate
operational endpoints. No volatility-normalized probability is assigned to them.

A dedicated parameterized-barrier probability model may be researched separately.
It must pass its own leakage-safe ablation and prospective validation before being
attached to these operational endpoints.

## Status

Predictive acceptance remains false. vNext4 is a new prospective epoch; vNext3
evidence is non-admissible for promotion.
