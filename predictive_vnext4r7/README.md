# BTC Predictive vNext4R7 remediation candidate

This branch is a **successor/remediation candidate** created after the independent
vNext4R6 audit. It does not rewrite or replace the live R6 evidence epoch.

Parent R6 prospective source:
`98d6ea6e981b3306f397a9105babc2e5d66ac7a0`

Independent audit actions implemented here:

1. strict event-workflow content binding against the signed pre-start manifest;
2. incremental signed checkpoint design to remove full Cosign replay from the
   critical 15-minute path while preserving periodic full verification;
3. exact event uniqueness and slot/anchor/due/idempotency invariants;
4. persistent + separated volatility-episode semantics;
5. research-only tail/magnitude head in units of the frozen R6 volatility barrier.

The frozen R6 numerical artifacts remain unchanged and are not retrained here.
The tail head is research-only and cannot enter production without a new immutable
source, pre-start registration, independent review, and its own prospective epoch.

`prospective_start_utc` is intentionally unset. This branch must pass remediation
tests and independent audit before any production workflow is activated.
