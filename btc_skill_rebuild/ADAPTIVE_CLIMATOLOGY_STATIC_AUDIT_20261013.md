# BTC v7R6: adaptive climatology source audit

Research only. No production, signed epoch or historical results modified.

The source file `research_adaptive_climatology_v7r6.py` at blob `3612b05d556d4d7dbc58faa32ef580a099ec8313` contains two literal `\\n` sequences between Python dictionary items near `source_asof_maturity_enforced` and `same_timestamp_maturity_excluded`. These are invalid Python syntax, not actual line breaks. Until fixed, the historical benchmark cannot be imported or tested. This is a static source finding, not a passed runtime test.

The rolling 7/14d climatology correctly intends to exclude labels whose maturity equals the issue timestamp (`bisect_left` on maturity), and uses horizon-spaced due timestamps. This intent still requires executable tests and raw-data evaluation. No prospective sample exists before 2026-10-13 00:00 UTC. Trading authority remains false.
