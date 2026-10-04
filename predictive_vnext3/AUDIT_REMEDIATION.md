# BTC Predictive vNext3 — remediation of independent REWORK audit

This branch supersedes the non-admissible vNext2 prospective registration.

## Audit defects addressed

1. **Signed freeze authority**
   - The signed pre-start `CONFIG_FROZEN_PRESTART` event is the sole freeze authority.
   - Every forecast and every outcome verifies the signed manifest hash and every frozen path.
   - The workflow path used by the current run must hash to the value in the signed manifest.
   - Production workflows restore executable sources from one immutable source commit before execution.
   - The prospective scorecard independently re-checks each event's recorded workflow commit against the frozen workflow hash.

2. **Overlapping outcomes**
   - Raw forecast count is never sufficient for admission.
   - 15m/4h gate: at least 42 calendar days, at least 150 fixed-phase non-overlapping 4h windows, at least 12 volatility episodes spanning all three bins.
   - 1h/72h gate: at least 90 calendar days, at least 30 fixed-phase non-overlapping 72h windows, at least 12 volatility episodes spanning all three bins.
   - Uncertainty uses both 14-day and 28-day blocks.

3. **No historical winner declaration**
   - Logistic, GBDT and competing-risks are frozen side by side.
   - No contender is called champion before future prospective evaluation.
   - Admission corrects for three simultaneous contenders.

4. **Exact prospective control**
   - Primary control is fixed before start: the exact vol90d same-volatility-bin rule used in historical research.
   - Secondary control is frozen training class frequency.
   - The primary control is seeded pre-start and can update only from outcomes whose due time is strictly before the current forecast anchor.

5. **Operational price question stays separate**
   - 82,500 before 87,000 / 72h and 81,500 before 88,000 / 168h are tracked as separate operational endpoints.
   - vNext3 does not claim that the volatility-normalized target is automatically a calibrated probability for those fixed price corridors.

6. **Early warning**
   - Each contender freezes lower/upper alert thresholds derived only from the historical calibration block at target FPR 20%.
   - Prospective reporting breaks recall, precision and FPR out by frozen volatility bin.

## Admission rule

A contender remains `PREDICTIVE_ACCEPT=false` unless it beats the preregistered primary control on both multiclass Brier and Log Loss, passes the calendar/non-overlap/episode gates, has positive family-wise corrected bootstrap lower bounds under both 14-day and 28-day blocking, and does not materially degrade calibration.

No production trading authority is granted by this epoch.
