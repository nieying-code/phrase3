# Phase 6 M2 C1–C2 Threshold Refinement Preregistration

## Purpose

The completed M2 V1 grid found zero autonomous reserve under C1 (`loss_scale=0.2`) and stable, near-boundary activation under C2 (`loss_scale=0.6`). This protocol refines that fixed interval without changing the model or searching adaptively after observing new results.

This revision is design-only. Its status is `candidate_design_pending_review`; it does not authorize scenario generation, Gurobi calls, development execution, pilot execution, multi-item confirmation, or formal extension experiments.

## Frozen refinement grid

The new profiles are fixed before execution:

| Profile | loss scale | recovery fraction |
|---|---:|---:|
| T03 | 0.3 | 0.0 |
| T04 | 0.4 | 0.0 |
| T05 | 0.5 | 0.0 |

The design uses the same three development seeds and three budget factors as the parent grid. Reusing these development seeds is intentional: it preserves strict common-random-number pairing with the already approved C1/C2 anchors. It does not create additional independent statistical samples.

The new matrix contains `3 seeds × 3 beta values × 3 profiles = 27` configurations. All 27 must run in frozen order if a later runner PR is approved; no adaptive early stopping or profile insertion is allowed.

## Gate definitions

For every beta–profile combination, all three seeds must be optimal and all endpoint/fixed-policy evidence must be complete. Activation requires at least two seeds with:

`R_disc_robust / B >= 0.01`.

The first ascending loss scale that passes defines the upper endpoint of the refined activation bracket; the preceding tested scale (or the C1 anchor at 0.2) defines the lower endpoint.

To distinguish a potentially interpretable interior response from another boundary jump, a separate descriptive gate requires at least two seeds with autonomous reserve ratios in the preregistered inclusive interval `[0.05, 0.50]`. The 5% and 50% values are management-relevance bounds, not statistical significance thresholds.

## Decisions fixed before results

- If no new profile activates, retain `(0.5, 0.6]` as the unresolved bracket and stop.
- If activation occurs but no profile passes the moderate-reserve gate, report a state transition/boundary response and stop parameter refinement.
- If a profile passes both gates, it may support a separately reviewed multi-item confirmation design; it does not authorize that experiment.
- Cost, service level, P95, CVaR95, runtime, and manual trend interpretation cannot select a configuration.
- New loss scales may not be added after results under this protocol.

## Reproducibility and isolation

The parent audit and both mapping hashes are immutable anchors. A future runner must use an independent namespace, output root, fingerprints, registry, projection, immutable run IDs, and explicit execution authorization. Parent results cannot authorize the refinement run and cannot be copied into its registry.
