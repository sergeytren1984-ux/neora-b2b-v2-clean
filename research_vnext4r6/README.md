# BTC Predictive R6 — research phase

R6 is a new research epoch built from immutable R5 source SHA
`16c4fd69e6c4e6f58310ecbd597daa80af270f83`.

R5 is not modified.

## Structural phase

R6 first tests:
- separate 1h / 4h / 24h heads;
- volatility-scaled first-passage barriers;
- the existing logistic / GBDT / competing-risks contenders;
- the strong adaptive `vol90d` baseline;
- two predeclared deterministic regime selectors.

A selector is not accepted merely because it wins one period. The research report
requires multi-fold chronological evidence. Production freeze and trading authority
remain false.

## Exogenous phase

Macro/context features are evaluated separately so that DXY, Nasdaq futures, US10Y,
funding/OI, ETF flows and macro-event context cannot silently improve a backtest by
timestamp leakage. Only features with documented observation/publication semantics
and successful ablation may be merged into a future frozen R6 candidate.

## Governance

R6 research results do not modify R5 evidence, outcomes, thresholds or workflows.
A clean prospective R6 epoch may be created only after research, negative tests,
independent review and a new pre-start registration/freeze.
