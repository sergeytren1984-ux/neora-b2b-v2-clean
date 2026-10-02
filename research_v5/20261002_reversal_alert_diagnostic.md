# Exploratory reversal condition diagnostic — 2026-10-02

This analysis was performed **after** seeing the prospective 2026-10-02 15:00 UTC directional-v1 alert. It is therefore exploratory and cannot be used as untouched validation or as a retroactive change to the frozen epoch.

Target: Binance BTCUSDT spot close after 4h more than 1% above anchor close. Model: frozen logistic upside candidate trained on 2024–2025; alert at or above rolling 80th percentile of prior 720 scores. Condition: closed anchor 1h return <= -1%. Numbers from the same contiguous historical dataset and as-of feature evaluation used in `directional_alert_eval.py`.

| Period | Condition observations | Alerts | Alert target successes | Condition target successes |
|---|---:|---:|---:|---:|
| 2024–2025 training (in sample) | 494 | 349 | 92 | 114 |
| Jan–Jun 2026 validation | 121 | 86 | 23 | 31 |
| Jul–Sep 2026 late diagnostic | 16 | 12 | 0 | 1 |

At 2026-10-02 15:00 UTC, the live closed-hour return was -1.0144%, the directional-v1 candidate estimate was 0.129219, rank 0.943056, `alert=true`, reference 85,686.93 USDT, due 19:00 UTC. The contemporaneous separate v4 4h shadow class scores favored range (0.60897) over downside (0.21945) and upside (0.17158), with no calibrated probabilities. The v4 11:00 UTC 4h outcome was downside (-0.7076%), a miss for its range/up leaning.

The late condition has only 12 alerts, and the validation period points in a different direction. Do not infer that a post-drop alert is always false or impose a new suppression rule from these counts. Treat this live warning as experimental and conflicting, record the eventual outcome only after due, then assess temporal stability before any separately preregistered successor model. Never rewrite the signed v1 alert or earlier forecasts.
