# BTC Predictive vNext4 — decision after independent-audit remediation research

Date: 2026-10-04.

This note records the model-development decision **before the vNext4 prospective start**. It does not change the frozen vNext4 production epoch.

## 1. Exact frozen-artifact late diagnostic

The exact vNext4 artifacts were evaluated without re-fitting on inspected Jul-Sep 2026 history. This is diagnostic, not confirmatory.

### 15m ±1% / 4h, fixed-phase non-overlap, n=545

| Model | Brier | Log Loss |
| --- | ---: | ---: |
| causal vol90d baseline | 0.378421 | 0.694393 |
| logistic | 0.358474 | 0.658347 |
| GBDT | **0.354810** | **0.651558** |
| competing-risks | 0.359538 | 0.660079 |

The late diagnostic is encouraging for the frozen 15m head, but cannot be used as prospective proof because this historical period has already been inspected during the broader research program.

Early-warning thresholds are conservative rather than high-recall. On the same non-overlapping diagnostic sample, GBDT lower/upper recall is about 28.6%/24.6%, with FPR about 10.0%/10.7%. False alerts remain the majority of alerts. Therefore the early-warning head is useful only as a shadow diagnostic until prospective recall/FPR/precision and lead-time evidence accumulates.

### Hourly volatility-normalized 72h, fixed-phase non-overlap, n=27

| Model | Brier | Log Loss |
| --- | ---: | ---: |
| causal vol90d baseline | 0.667593 | 1.149835 |
| logistic | **0.583143** | **0.956084** |
| GBDT | 0.613962 | 0.999634 |
| competing-risks | 0.586849 | 0.963545 |

The sample is too small for promotion. Logistic also has materially worse ECE than the baseline in this diagnostic, so predictive discrimination and probability calibration must not be conflated.

## 2. Feature-family ablation

Five existing feature families were removed one at a time on the same chronological folds. No removal is sufficiently robust across model families to justify changing the frozen vNext4 model.

Important findings:

- `volatility_range` is consistently useful. Removing it materially worsens both logistic and GBDT, especially on 15m.
- 15m logistic shows a very small historical improvement when `returns_trend` is removed (mean Brier gain about 0.00081) and when `taker_flow` is removed (about 0.00052), but GBDT does not confirm those changes.
- 15m GBDT shows a small improvement without `structure_efficiency` (about 0.00116 mean Brier), while logistic does not confirm it.
- hourly logistic has small/model-specific removal signals for activity/taker features; they are not stable enough to justify feature deletion.

**Decision:** no feature family is removed from vNext4. The ablation result is kept only as a hypothesis generator for a separately frozen future challenger.

## 3. Separate operational fixed-barrier probability research

A generalized first-passage classifier was trained with lower-distance, upper-distance and horizon as explicit query inputs. This avoids assigning a volatility-normalized probability to a different fixed-price event.

Overall conditional-baseline comparison:

| Fold | Baseline Brier | Logistic | GBDT |
| --- | ---: | ---: | ---: |
| 2025Q3 | 0.580899 | **0.519656** | 0.552561 |
| 2025Q4 | **0.552778** | 0.591771 | 0.653483 |
| 2026H1 | 0.542760 | 0.543409 | **0.541064** |

Logistic has a clearly positive Brier-gain interval in 2025Q3, a clearly negative interval in 2025Q4, and no reliable advantage in 2026H1. GBDT is also unstable.

For the geometry closest to the current 72h operational question (~2.5% lower / ~3.0% upper), logistic mean Brier is 0.645167 versus baseline 0.665964, but it loses materially to baseline in 2025Q4. For the ~4% / ~4% 168h geometry, logistic mean Brier is 0.657645 versus baseline 0.660511, which is too small and unstable to support publication.

**Decision:** do not attach model probabilities to `82,500 before 87,000 / 72h` or `81,500 before 88,000 / 168h`. The operational endpoints remain outcome-only in vNext4.

## 4. Final pre-start model decision

No further numerical change to vNext4 is justified by the completed audit-driven research. Changing the frozen model now on the basis of these inspected diagnostics would increase selection bias and invalidate the clean prospective test.

Therefore:

- vNext4 remains frozen exactly as registered;
- predictive acceptance remains **false**;
- three contenders remain equal prospective candidates;
- no feature deletion is promoted;
- no fixed-price probability head is promoted;
- the next admissible evidence is genuinely future vNext4 forecast/outcome data.

Any new feature family or parameterized-barrier model must be a separately frozen future challenger and must beat the same preregistered adaptive baseline on future fixed-phase non-overlapping observations.
