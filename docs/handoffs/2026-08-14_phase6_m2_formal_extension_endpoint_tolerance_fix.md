# Phase 6 M2 formal-extension endpoint tolerance fix

## Outcome

The first `v1_0` technical-pilot batch finalized 15 mechanism runs and one
out-of-sample probe as `optimal`, but the final projection accepted only three
mechanism runs.  The projection compared the independently reevaluated reserve
face endpoint difference with the frozen objective tolerance using a strict
floating-point `>` comparison.

Across the 30 endpoint checks, 18 exceeded the serialized tolerance by a
positive amount.  The maximum excess was only
`1.5735617236306565e-11`.  This is below the existing `1e-8` numerical
comparison slack already used by the M1 development, M2 development, threshold
refinement, and two-item confirmation paths.  No solver failure, infeasible
recourse result, timeout, or incomplete finalization caused this condition.

## Minimal correction

`phase6_m2_formal_extension._derive_mechanism()` now accepts an endpoint only
when

```text
endpoint_consistency_difference
<= objective_tolerance + 1e-8
```

The `1e-8` term is a numerical comparison allowance for serialization and
independent exact reevaluation.  It does not replace or enlarge the frozen
scientific objective tolerance used to construct the tolerance-optimal face.
Values beyond the combined bound remain invalid and block the projection.

The regression test covers both sides of the boundary.  A read-only replay of
the validator against the retained `v1_0` artifacts accepts all 15 mechanism
runs under the corrected rule; it did not rewrite the old projection or any
run artifact.

The validator also requires the objective tolerance and both endpoint
differences to be finite and nonnegative before applying the comparison.
`NaN`, positive or negative infinity, and negative differences are therefore
invalid machine evidence and cannot pass through Python's unordered `NaN`
comparison behavior.

## Reproducibility and rerun boundary

The original `v1_0` run artifacts remain immutable diagnostic evidence.  No
pilot, formal experiment, scenario generation, or Gurobi solve was run by this
fix.

Because the corrected module is included in the protected E3 and family
component scopes, their fingerprints change.  The existing approval file is
deliberately not updated in this PR, so execution remains blocked by a
fingerprint mismatch.  After this fix is reviewed and merged, a separate
reviewed re-freeze must assign a new runner namespace/output root, update the
approval fingerprints, and explicitly authorize a fresh 16-run technical
pilot with new run IDs.  The retained `v1_0` batch must not be migrated into the
new gate.

## Fingerprints

| Fingerprint | Before | Corrected source tree |
| --- | --- | --- |
| scientific configuration | `fec4e4dde521692767f9ba48ec6809528f87856c59d2be0a082bcfa360980565` | unchanged |
| E3 component | `b80147591b26099f15794adf095549101d733a51780e076e0e8599ec591bed46` | `0c28af6e6bcfa43c5905cf4ff96e5ed2ee5e957eaf04411bb0c15eb25e32722e` |
| family component | `bf6dae9fc3d79a4906995d259b0aa5d50697eb00211072600369da839901be3c` | `5302cf053c9d9b580dd0cb2fa589909ab369ef5a5e426cb9f58a51f32b581905` |
| runner configuration | `76f54b5394406715b1974db1be6db49805f7c9458f8f886efc1010c7421fd3f0` | unchanged |
| environment | `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af` | unchanged |

Base commit: `ad0174fb11b45fe71e39982605cc6b85e5dc1691`

Base tree: `b90a533bc200a99e228d1170017dce60ab74b144`

The final PR head and CI run are recorded in the PR description to avoid
self-referential document commits.
