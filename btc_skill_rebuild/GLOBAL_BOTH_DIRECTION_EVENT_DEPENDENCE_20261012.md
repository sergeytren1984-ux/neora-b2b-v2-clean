# BTC v7R6 — global direction-agnostic episode sensitivity, 2026-10-12

Research-only mathematical analysis of 18,720 previously studied closed Binance 5m BTCUSDT candles. Source gzip SHA256: b590c60a8224bb15ac78fd28361954cd7e21825cb29a1aaa6758c801efe4fe7b.

Four fixed seven-day historical test weeks: 2026-09-14, 09-21, 09-28, 10-05 UTC. Same previously established 1h +/-0.7% and 4h +/-1.2% first-touch barriers. Episodes connect consecutive distinct first-touch timestamps separated by no more than the original horizon, **irrespective of UP/DOWN**, across weekly boundaries.

| Horizon | Fixed due | Resolved due | Missing/immature | Global distinct touch+side | Global same-side clusters | Global both-side clusters | Mixed-side clusters |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1h | 2688 | 2664 | 24 | 198 | 115 | **89** | 21 |
| 4h | 2688 | 2652 | 36 | 169 | 52 | **40** | 10 |

Earlier same-side weekly sums 116/53 are not globally independent. The additional reduction to 89/40 is an even more conservative **descriptive** event count, not a guarantee of independence. The 21/10 mixed-direction clusters demonstrate why nearby opposite first touches may share the same underlying volatility episode.

Seven adversarial mathematical tests passed on the authorized Mac. The full fixed due grid is retained, including incomplete windows. Historical OHLC cannot resolve same-candle barrier order; no retrospective fill or public warning is claimed.

**Not prospective. No new predictive or OTC advantage established. Trading authority: false.** Require at least 20 prospective day blocks and independent events, positive conservative statistical bounds and actual operator execution evidence before considering admission.