# BTC Predictive v7R6: event-dependence math audit, 2026-10-12

Scope: retrospective mathematical research only. No changes to frozen v7R5/v7R6, production signals, infrastructure or trading. All 18,720 Binance 5m candles were already known; not prospective.

## Confirmed methodological defect

The previous globally deduplicated `grouped_episodes()` uses same-side single-link clustering: each later first touch within one horizon of the PREVIOUS touch extends the episode. Consequently an episode can exceed the stated 1h/4h horizon. UP and DOWN are also grouped separately, potentially double-counting one reversal episode.

A fixed-FIRST-touch horizon anchor prevents transitive chaining. A second variant clusters both signs together to avoid treating reversals inside the same horizon as independent events. Neither variant proves stochastic independence.

Original gzip SHA256: `b590c60a8224bb15ac78fd28361954cd7e21825cb29a1aaa6758c801efe4fe7b`.

| Retrospective count, identical first-touch labels | 1h | 4h |
| --- | ---: | ---: |
| Predefined 15m due slots | 2664 | 2652 |
| Directional overlapping due | 331 | 496 |
| Unique (first-touch timestamp, direction) | 198 | 169 |
| Original globally deduped same-side single-link | 115 | 52 |
| Chains spanning beyond fixed horizon | 6 | 5 |
| Longest original chain, minutes | 100 | 520 |
| Fixed-anchor same-side episodes | 121 | 57 |
| Fixed-anchor both-sides nonoverlapping windows | 107 | 50 |
| Both-sides windows containing UP and DOWN | 18 | 9 |

The previously published 116 and 53 were WEEKLY SUMS, not global counts. Even the corrected 115 and 52 should not be described as verified independent price innovations. The both-sides 107 and 50 are deterministic nonoverlapping windows, not statistically independent trials.

Exact committed Python research module and its 13 adversarial/invariance tests were executed on the Mac against the actual historical gzip; 13/13 passed. No changes to target labels, barriers, trained weights, probability forecasts or frozen evidence.

No new prospective observation, Brier improvement, price advantage, 60-minute warning or actual operator OTC edge was produced. Admission remains `trading_authority=false`. Require at least 20 independent FUTURE UTC day blocks, unique events, verified timely forecasts and statistically robust positive REAL OTC net benefit.

Reproduce with `python3 -m unittest btc_skill_rebuild.test_research_event_dependence_bounds_v7r6 -v` and `python3 -m btc_skill_rebuild.research_event_dependence_bounds_v7r6 --raw DATA.gz --out result.json`.
