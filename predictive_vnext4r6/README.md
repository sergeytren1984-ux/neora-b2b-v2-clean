# BTC Predictive vNext4R6 — frozen research candidate

This directory is a **research-candidate freeze**, not a trading system and not a
prospective admission.

Parent R5 immutable source: `16c4fd69e6c4e6f58310ecbd597daa80af270f83`.

The candidate is created only if
`research_vnext4r6/research_gate_result.json` has status
`READY_FOR_FREEZE_RESEARCH_CANDIDATE`.

## Frozen core

Three independent heads are frozen:

- 1h — 15m spot features, realized-volatility-scaled first-passage target;
- 4h — 15m spot features, realized-volatility-scaled first-passage target;
- 24h — 1h spot features, realized-volatility-scaled first-passage target.

For all three heads the selected research architecture is
`ensemble_equal`: equal-weight mean of calibrated logistic, GBDT and
competing-risks component distributions.

The final artifact fit intentionally reuses the exact train/calibration partition
that produced the untouched 2026Q3 historical evaluation:

- model-fit labels due before 2026-01-01 UTC;
- calibration anchors from 2026-01-01 with labels due before 2026-07-01 UTC;
- 2026-07-08..2026-09-24 remains historical validation evidence and is not reused
  for the frozen component fit.

This makes the frozen artifact directly traceable to the research result instead of
silently retraining on the historical validation fold.

## Optional blocks

The first freeze excludes optional blocks from the executable candidate:

- DXY / Nasdaq futures / US10Y daily-market block — rejected by the paired gate;
- funding/OI block — rejected by the paired gate;
- breakout-memory block — historically passed only for the 1h GBDT ablation, but
  has not yet been proven incrementally against the selected 1h equal-weight
  ensemble;
- regime selectors remain research diagnostics and are not substituted for the
  selected ensemble after inspection of the test folds.

The 1h breakout-memory result is preserved for a future paired
selected-ensemble ablation. It is not silently mixed into this freeze.

## Authority

`trading_authority = false`
`prospective_admission = false`

A prospective R6 launch requires a separate pre-start protocol, immutable source
registration, negative tests, independent review, and signed evidence setup. R5 is
not modified by this branch.
