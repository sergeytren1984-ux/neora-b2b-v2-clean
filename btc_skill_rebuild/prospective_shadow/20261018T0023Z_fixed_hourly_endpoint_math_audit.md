# Research-only BTC v7R6 mathematical endpoint audit (2026-10-18 00:23Z)

Original fixed HH:00Z due grid: 121 due, 63 R5 source snapshots present, 58 missing. Six public research forecasts committed by HH:13Z, 115 missing. The 2026-10-18 00:00Z source exists but research forecast was absent after deadline and is permanently MISSING. Off-hour 2026-10-13 04:45Z excluded.

All 17 matured endpoints of the six public HH:00Z forecasts were independently checked against an exact closed 5m candle in later R5 snapshots: 1h n=6 (5 RANGE, 1 DOWN), 4h n=6 (6 RANGE), 24h n=5 (4 RANGE, 1 DOWN). No prospective endpoint is silently omitted from the fixed due denominator. No cryptographic Cosign verification is claimed.

Paired Brier mean (lower better), frozen training prior versus published research probabilities: 1h 0.103248563900 versus 0.099657028873, gain +0.003591535027; 4h 0.003913287903 versus 0.003386405066, gain +0.000526882837; 24h 0.119148303526 versus 0.119148303526, gain 0. All are descriptive, not statistical evidence of skill.

Exact day-block bootstrap 95% intervals for gain (prior minus model): 1h [-0.000865393472, 0.013554344441], 4h [0, 0.001896778214], 24h [0, 0]. There are at most five distinct publication days. The sole 1h DOWN outcome on Oct 15 supplies the apparent mean gain; omitting that day reverses mean 1h gain to -0.000208272781. The entire 4h gain comes from the Oct 17 02:00Z forecast, already known to fail parity with original pinned predictor blob 9709e5c8b886f4f362fd003d0af91f74e3e9dc38; it must not be credited as frozen model alpha. 24h frozen shrink=0 produces no added skill.

This audit is math-only. No model, frozen data, original forecast, infrastructure or trading instruction changed. Signed source not independently Cosign verified. No actual OTC firm asks or fills. Independent >=20-day criterion unmet. trading_authority=false.
