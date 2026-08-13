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

Threshold identification is performed independently for each budget factor (`beta=0.9`, `1.1`, and `1.3`). Within each beta, the frozen order is `C1, T03, T04, T05, C2`. The approved parent evidence is locked separately by beta: C1 has 0/3 substantive activations and C2 has 3/3 substantive activations at every beta.

The first ascending loss scale that passes defines the upper endpoint of that beta's refined activation bracket; the preceding tested scale defines its lower endpoint. A bracket is reported only when the binary activation sequence is monotone nondecreasing: once activation occurs, later profiles may not return to inactive. A sequence such as inactive-active-inactive is recorded as `nonmonotone_activation_pattern`; that beta produces neither a threshold bracket nor a multi-item candidate. Numerical reserve ratios themselves need not be monotone.

To distinguish a potentially interpretable interior response from another boundary jump, the moderate gate is the logical conjunction:

`moderate_gate_passed = combination_activation_gate_passed AND moderate_seed_count >= 2`.

The moderate interval is the preregistered inclusive range `[0.05, 0.50]`. The 5% and 50% values are management-relevance bounds, not statistical significance thresholds. A moderate count can never pass by itself when a run failed or the full combination activation gate did not pass.

## Decisions fixed before results

- If none of the nine beta-profile combinations activates, report no intermediate activation and stop.
- If at least one combination activates but none passes the conjunctive moderate gate, report a boundary transition and stop.
- If at least one combination passes both activation and moderate gates, it may support a separately reviewed multi-item confirmation design; it does not authorize that experiment.
- Any beta with a nonmonotone activation pattern is excluded from threshold reporting and multi-item candidate selection, regardless of other metrics.
- Cost, service level, P95, CVaR95, runtime, and manual trend interpretation cannot select a configuration.
- New loss scales may not be added after results under this protocol.

## Reproducibility and isolation

The parent audit and both mapping hashes are immutable anchors. A future runner must use an independent namespace, output root, fingerprints, registry, projection, immutable run IDs, and explicit execution authorization. Parent results cannot authorize the refinement run and cannot be copied into its registry.
