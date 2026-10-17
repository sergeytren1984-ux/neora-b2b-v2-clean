# BTC v7R6: immutable 02:00Z forecast alpha parity attribution

Research-only; no trading authority. The 2026-10-17 02:00Z public probabilities differ from the exact precommitted original predictor code (blob 9709e5c8b886f4f362fd003d0af91f74e3e9dc38), as established in 20261017T1009Z_frozen_original_code_alpha_parity_failure_research.json. For exact 5-minute RANGE endpoints at 03:00Z and 06:00Z, the three-way Brier scores (mean squared across 3 classes) are:

| Horizon | Published Brier | Ex-post original-code Brier | Published minus original |
|---|---:|---:|---:|
| 1h | 0.001798392928 | 0.000171890636 | +0.001626502293 |
| 4h | 0.000751990880 | 0.003913287903 | -0.003161297023 |

The apparent 4h gain of 0.003161297023 over the frozen prior is wholly attributable to the alpha inversion, not proven skill of the pinned code. The ex-post original-code probabilities were never published prospectively and cannot replace the published values or enter a prospective skill estimate. The 24h endpoint (18 October 02:00Z) is not yet mature.

Original fixed hourly grid through 17 October 15:00Z inclusive: 112 due, six on-time published research forecasts, 106 missing. The 15:00Z R5 snapshot exists, but its research forecast was absent after HH:13Z and must remain missing. At most five publication days, no independent Cosign verification, no actual OTC firm asks or fills. trading_authority=false.
