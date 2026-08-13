# Phase 6 M2 Threshold-Refinement Runner Handoff

## Outcome

Implemented the frozen, independently authorized runner for the 27 preregistered T03/T04/T05 configurations. No scientific run was executed.

## Safety boundary

- Protocol/namespace: `phase6_m2_threshold_refinement_v1_0`.
- Output root: `outputs/phase6_m2_threshold_refinement_v1_0`.
- Parent C1/C2 evidence is read-only and hash verified.
- Parent registry/projection import is forbidden.
- Explicit CLI authorization and frozen lifecycle state are both required.
- Runs are strictly serial and immutable; failures stop the matrix.
- Projection always records `formal_extension_authorized=false`.

## Scientific gate implementation

- Activation is recomputed from reserve-face raw values rather than stored booleans.
- Endpoint exact-recourse evidence and four fixed-policy reoptimizations are required.
- Common-random-number hashes are compared against C1 per seed and beta.
- Each beta independently evaluates `C1,T03,T04,T05,C2`.
- Nonmonotone activation excludes that beta from threshold and multi-item candidates.
- Moderate activation is the conjunction of combination activation and at least two moderate seeds.

## Execution counts

Refinement development runs, pilots, formal extensions, multi-item confirmations, and M0 E3 runs in this PR are all zero. Scenario generation count and Gurobi call count are zero.

## Traceability

- Base: PR #46 merge `9cdd7bb8d735cc82590ac25f2227b84e17ada2af`.
- Branch: `agent/phase6-m2-threshold-refinement-runner`.
- Draft PR: pending.
- Final commit and CI: pending.
- Local validation: threshold-runner specialized `10 passed`; ordinary regression `294 passed`; Phase 5 `6 passed`; compileall and `git diff --check` passed.
