# BTC v7 — demand, positioning, future prices and OTC execution

## Implemented on 11 October 2026

**Status: RESEARCH SHADOW / NO VERIFIED PRICE EDGE / NO TRADING AUTHORITY.**

All code, tests, audits, OIDC Cosign/Rekor signatures, and experimental live
inference are on GitHub. No AWS, paid data service, user keys or automated
BTC orders.

- New numerical head: one jointly managed research candidate with closed
  Binance 5m and 1m price/volume/taker flow plus lagged historical Binance
  USDT-M/COIN-M open interest and funding. The historical Mac-retrieved
  derivative records do not prove point-in-time release by the venue.
- Separate **source-compatible online shadow** uses exclusively closed
  Binance spot 5m+1m model inputs. Current OKX OI, funding and top-of-book
  observations appear as independent context; OKX data MUST NOT be silently
  substituted for Binance historical OI features.
- Direct point-price outputs: 1h, 4h, next 08:00 MSK. Additional execution
  endpoints: 2h, 5h, next 09:00 MSK.
- Rare-move risk outputs, symmetric up/down: 30m (0.45%), 1h (0.7%),
  and 4h (1.2%); validation-only alert threshold, not trade probabilities.
- OTC engine: same 147,600 USDT starting cash; buying NOW means an operator
  order filled in approximately one hour, not an instantaneous fill.
  WAIT_1H means place order after one hour and fill at +2h; WAIT_4H
  means fill at +5h; wait until next 08:00 MSK means fill around
  next 09:00 MSK. Premium parameter defaults to 350 USDT/BTC
  (support 300–400 sensitivity). The prices are indicative,
  NOT binding OTC quotes; further intra-hour slippage is not modeled.
- Paired historical validation residuals are used as a rough sensitivity
  analysis with dependence intact, **not a calibrated trading interval**.

## Evidence and exact status

- [Successful frozen training, no-lookahead and negative OTC tests](https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/actions/runs/38169934478)
  on frozen Git commit `3d08e5a767f1848a9e10d6bea1ef939c2b77238a`.
  Full numerical model, evaluation and paired OTC scenarios signed
  with keyless Cosign and Rekor.
- [First successfully signed complete live shadow](https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/actions/runs/38170130611):
  exact signed frozen training model AND signed OTC scenario bundle verified
  before inference, live raw/derived receipts signed afterward.
  First sample anchor 2026-10-11 19:55 UTC (22:55 MSK);
  spot BTCUSDT 83,672.65. Forecasts for all requested future horizons
  equal the spot baseline; experimental event probabilities are NOT
  actionable. At 350 USDT/BTC OTC markup, every modeled fill yields
  1.75666918 BTC on 147,600 USDT, **NO_VERIFIED_EDGE**.
- [15-minute research dispatcher on GitHub main](https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/actions/runs/38170056335):
  accepted and completed. GitHub dispatches
  `btc-v7-shadow-snapshot.yml` on the research branch approximately
  every 15 minutes using native GitHub Actions. GitHub schedule can
  queue/delay or drop executions; **never claim a guaranteed 15m SLA**.
  Actual raw receipt timestamp (not planned slot) is authoritative.
  There is no backfill. Every completed snapshot has OIDC and Rekor
  inclusion evidence.
- [First signed market snapshot](https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/actions/runs/38169484900).
  [Test of the automatic dispatcher resulting in another successful snapshot](https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/actions/runs/38170062767).
- Existing R4.3/R4.4 signed production journals were not altered.
  R7 is **not** replacing the old production algorithm and has no
  external trade control.

## Numerical quality: present negative finding

On Oct 5–11 held-out historical 5m windows, the candidate's calibrated
regressors did **not** beat the persistence price baseline on any of the
six point forecasts. Their validation-selected shrinkage was zero.
This is a genuinely negative price result, not an engineering fault.

Example model MAE on overlapping 5m test windows:
- 1h: approximately 171.93 USDT;
- 4h: approximately 347.80 USDT;
- next 08:00 MSK: approximately 576.51 USDT.

Overlapping 5m observations are strongly dependent; the effective
independent sample count is smaller. Already-discussed 11 October
18:45 MSK surge is an **adversarial diagnostic**, not unseen
future evidence. Re-running training until that event looks predictable
is expressly forbidden.

## Source priority and provenance

REQUIRED: closed Binance 1m+5m (exact grid; stale or gap -> FAIL).
OPTIONAL: current aggregated BTC contracts OKX OI, OKX funding,
OKX swap order book. Missing secondary sources -> record UNAVAILABLE,
not fabricated zero. For book snapshots, reject stale and future
vendor timestamps. Only the historical Binance OI model uses the
Binance derivatives records numerically, and it is not authorized
as the source-compatible online model.

Numerical macro, news, ETF, liquidations and independent order-flow
must wait for an archived pre-event as-of feed before inclusion.
Narrative market observations cannot be asserted to influence
a probability if they are outside the executable feature vector.

## Next acceptance gates before live OTC buy/wait authority

1. Accumulate **prospective timestamped signed** OI, book spread and
   imbalance, spot flow and future outcomes. Score coverage of every
   planned 15m window; actual gaps count as gaps.
2. Freeze one candidate + causal feature schema + alert thresholds
   before the prospective evaluation; no favorable retuning based
   on 11 October event. Score 30m/1h/4h impulse Brier, PR-AUC,
   false alerts/day, missed surges, direction and calibration.
3. Future point-price MAE and bias must beat simple persistence,
   momentum baseline and identical execution costs on unseen windows
   for 1h, 4h, 08:00 MSK.
4. Measure realized BTC units and downside/missed-entry regret
   under identical 147,600 USDT cash, 300–400 USDT/BTC OTC markup,
   and one-hour order execution delay; compare buy now, wait 1h,
   wait 4h and wait until 08:00 MSK.
5. No promotion without statistically defensible positive result,
   signed evidence, enough genuinely independent future outcomes,
   and conservative economic benefit after OTC costs. Keep
   `prospective_skill_proven=false` and `trading_authority=false`
   until these gates are satisfied.

## Explicit limitations

A successful GitHub run or a Sigstore/Rekor inclusion proof establishes
integrity and temporal provenance, NOT accurate future prices.
Live inference at +1h/+4h is anchored to the **last closed 5m candle**;
OTC schedule starts when the live inference is emitted, offset
by a few minutes. This timing mismatch is surfaced in the JSON and
prevents these raw point estimates from becoming execution-ready quotes.
No orders were sent or placed.
