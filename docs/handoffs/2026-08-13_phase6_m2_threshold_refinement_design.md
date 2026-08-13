# Phase 6 M2 Threshold Refinement Design Handoff

## Goal

Preregister a small C1–C2 threshold-refinement experiment after the approved M2 V1 development grid. No experiment is executed in this PR.

## Design

- Parent anchors: at each beta, C1 loss scale 0.2 has 0/3 activation and C2 loss scale 0.6 has 3/3 activation (0/9 and 9/9 in total).
- New fixed profiles: 0.3, 0.4, and 0.5.
- Seeds: 2026081201, 2026081202, 2026081203.
- Budget factors: 0.9, 1.1, 1.3.
- New configurations: 27.
- Execution mode: future strictly serial development runner only.

The same development seeds are reused solely for paired common-random-number comparisons against C1/C2; they are not treated as new independent samples.

## Decision rules

Combination activation requires 3/3 optimal runs and at least 2/3 substantive activation (`R_disc_robust/B >= 0.01`). The moderate-response gate is not independent: it requires the complete combination activation gate to pass **and** at least 2/3 ratios in `[0.05, 0.50]`.

Thresholds are identified separately for beta 0.9, 1.1, and 1.3 in the fixed order `C1, T03, T04, T05, C2`. Only a monotone inactive-to-active binary sequence may yield a bracket. A return to inactivity is recorded as `nonmonotone_activation_pattern`, and that beta is excluded from threshold and multi-item candidate selection. Reserve ratios need not themselves be monotone.

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
- Initial design implementation commit: `dd47401`.
- Draft PR: https://github.com/nieying-code/phrase3/pull/46.
- Local validation after review fixes: design audit `2 passed`; ordinary regression `284 passed`; Phase 5 `6 passed`; compileall and diff check passed.
- Reviewed design head: `8b859c0f41f438f22db0948818c18071cd71c3f0`.
- GitHub Actions: run [31664853790](https://github.com/nieying-code/phrase3/actions/runs/31664853790), Linux and Windows successful.
