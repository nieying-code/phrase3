# Phase 6 M2 Threshold Refinement Design Handoff

## Goal

Preregister a small C1–C2 threshold-refinement experiment after the approved M2 V1 development grid. No experiment is executed in this PR.

## Design

- Parent anchors: C1 loss scale 0.2 (0/9 activation) and C2 loss scale 0.6 (9/9 activation).
- New fixed profiles: 0.3, 0.4, and 0.5.
- Seeds: 2026081201, 2026081202, 2026081203.
- Budget factors: 0.9, 1.1, 1.3.
- New configurations: 27.
- Execution mode: future strictly serial development runner only.

The same development seeds are reused solely for paired common-random-number comparisons against C1/C2; they are not treated as new independent samples.

## Decision rules

Combination activation requires 3/3 optimal runs and at least 2/3 substantive activation (`R_disc_robust/B >= 0.01`). A separate moderate-response gate requires at least 2/3 ratios in `[0.05, 0.50]`.

No result-dependent parameter insertion is allowed. If activation remains a near-100% jump, the mechanism is reported as a state transition rather than a calibrated reserve recommendation.

## Isolation and stop boundary

- Protocol: `phase6_m2_threshold_refinement_v1_0`
- Namespace: `phase6_m2_threshold_refinement_v1_0`
- Output root: `outputs/phase6_m2_threshold_refinement_v1_0`
- Status: `candidate_design_pending_review`
- Refinement runs, pilots, formal runs, multi-item runs, and M0 E3 runs in this PR: all 0.
- Formal extension authorization: false.

## Review focus

1. Whether 0.3/0.4/0.5 is a sufficiently small, non-adaptive refinement of `(0.2,0.6]`.
2. Whether the activation and moderate-response gates are fully machine-defined.
3. Whether reuse of development seeds is correctly limited to paired mechanism evidence.
4. Whether stop rules prevent further parameter chasing.

## Traceability

- Base merge: PR #45, `aa3a3aa48e44cc5978afdc08da2d380a1fa4c4b0`.
- Branch: `agent/phase6-m2-threshold-refinement-design`.
- Draft PR: pending.
- CI: pending.

