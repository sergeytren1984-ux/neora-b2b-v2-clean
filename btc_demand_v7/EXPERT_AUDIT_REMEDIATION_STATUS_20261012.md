# BTC v7 — response to independent audit, 12 October 2026

**Source:** uploaded BTC_v7_Independent_Audit_20261011.md, expert verdict REWORK / NO.
**Status:** partial technical remediation only; **NO PREDICTIVE SKILL**, **NO TRADING AUTHORITY**. No new clean prospective epoch has been registered. No changes to frozen R4.3/R4.4 production contour or its signed evidence. All changes here are on a separate research branch.

## Evidence actually checked

- Original expert-analyzed commit: `076c2963c0dcb174b63c858906d901cae812657e`.
- [GitHub signed negative regression run 38204382597](https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/actions/runs/38204382597) **success**, with OIDC/Rekor receipt. Verified signed model/audit/scenario artifacts; exact allowed model source SHA `3d08e5a767f1848a9e10d6bea1ef939c2b77238a`. Negative mutations rejected in the actual inference path.
- [GitHub full live shadow run 38204591089](https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/actions/runs/38204591089) **success**: signatures verified, SHA release pin passed before deserialization; fresh market observations and forecast signed with Rekor inclusion. Reference close 2026-10-12T04:35Z at 83,806 USDT. All six point prices remain 83,806; no verified skill.
- **OTC status is now `NO_EXECUTION_ALIGNED_FORECAST`** because forecast targets differ from actual order execution times; no quantities are asserted. This is a fail-closed fix, NOT a superior OTC strategy.
- Existing research dispatcher is NOT a 15-minute prospective protocol. Only two successful scheduled collection runs were observed overnight, 2026-10-11T23:28Z and 2026-10-12T02:34Z, so due-grid completeness is deficient.

## Explicit matrix of all 14 expert findings

| Finding | Status | Evidence / remaining requirement |
|---|---|---|
| V7-01 BLOCKER, forecast/OTC time shift | **Fail-closed guard implemented/tested** | Precise `forecast_target_utc`, order `due_utc`. On mismatch, no economic forecast. Exact executable alignment still needs a separately validated predictor at the execution timestamp. |
| V7-02 HIGH, inference accepts invalid raw | **Tested remediation** | Exact symbol, feed, anchored closed 1m/5m grids, receipt ordering, recomputed spot observation; future/gap/forgery tests PASS. |
| V7-03 HIGH, premature book cutoff | **Code patched, collector tests** | Individual request and receipt times; first full new-run was successful, but long-term provider coverage must be tracked. |
| V7-04 HIGH, funding instrument/ts | **Code patched and negative tests PASS** | Exact OKX swap instrument, finite rate, observation timestamp. Future settlement time is legitimate and not confused with observation time. |
| V7-05 HIGH, release mixing | **Partially remediated** | Exact model/audit/residual hashes and signer source SHA checked before joblib; action download/upload revisions pinned in live workflow. Wheel hashes and immutable signed pre-release manifest policy across all workflows still missing. |
| V7-06 HIGH, unsigned original historical training input | **OPEN** | Existing historical input verification in original TRAIN workflow remains insufficient. Before any *new* training release, verify signed raw5m/raw1m/futures inputs with source SHA and fail-on-tamper. |
| V7-07 HIGH, full prospective grid/forecast/outcome | **OPEN — BLOCKS NEW EPOCH** | Existing dispatcher only collects snapshots, has sparse schedule; there is no v7 outcome worker or complete due grid. Do not count as prospective model accuracy. |
| V7-08 HIGH, price shrinkage=0 | **MATHEMATICAL FAILURE CONFIRMED** | All six point estimates still equal current spot. Baseline-only label explicit; cannot declare solved by infra changes. |
| V7-09 HIGH, no early up warning | **MATHEMATICAL FAILURE CONFIRMED** | up_1h/up_4h zero successful hourly alerts on historic test. Rejected heads now show NOT_VALIDATED and cannot emit actionable `watch`. Need new as-of features and independent future validation. |
| V7-10 HIGH, OTC rejects/delays/slippage | **OPEN** | Old proxy assumed guaranteed fixed one-hour fill. Need quote acceptance/rejection and delay model before comparing economic actions. |
| V7-11 MEDIUM, nonfinite paired OTC residuals | **Tested remediation** | NaN/inf validation, fail-closed; allow_nan=False in forecast JSON. |
| V7-12 HIGH, oracle test prior/overlap | **OPEN** | Rebuild scorecard with frozen TRAIN prior, clustered independent events, power/CI, global alert budget. Historic Oct5–11 no longer untouched. |
| V7-13 MEDIUM, asymmetric up/down semantics | **OPEN** | Must pre-register symmetric onset and first-touch competition; old binary heads not a three-way outcome. |
| V7-14 HIGH, unsigned numerical binding in forecast | **Partially remediated** | Signed live forecast now embeds raw snapshot SHA256, model/audit/paired SHA256, training source commit/run, inference commit/run, exact future target times. Signed outcome hash link not possible until V7-07 implemented. |

## Required order — forecast quality takes priority

1. Keep user-facing trading authority and verified skill **FALSE**. Never present a green GitHub run as predictive advantage or a hypothetical OTC quantity as an executable quote.
2. Finish and re-audit V7-01 positive execution-time target alignment + V7-05/06/07 signed evidence grid/outcomes; DO NOT force-accept or backfill yesterday's candles.
3. Build **one** causally timestamped as-of dataset of OKX OI/book/spread, spot taker flow and eventual outcomes BEFORE any further probability optimization. Missing factors and queue delays are explicit lost coverage.
4. Freeze economic primary action (buy now, wait 1h/4h/morning), cost/acceptance assumptions, alert budget, lead-time and first-touch label semantics before new untouched future data. Power sample count must follow observed independent rare events, not an arbitrary 30-day promise.
5. Only consider numerical promotion if concrete price MAE improves versus persistence and frozen momentum; impulse detection has positive calibrated event-level lead-time with false-alarm constraint; buy/wait has a positive lower confidence bound of net BTC gain after identical OTC costs and execution risk. Otherwise REJECT.

Do not tell the user that 18 October or 10 November is a guaranteed effectiveness verdict. Until V7-07 and independent prospective evidence operate, these dates have no statistical basis.
