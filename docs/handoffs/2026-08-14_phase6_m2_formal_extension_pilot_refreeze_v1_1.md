# Phase 6 M2 formal-extension technical-pilot re-freeze v1.1

## Outcome

This change re-freezes the unchanged 15-run mechanism pilot and one-run OOS
throughput probe after the endpoint-tolerance validator fix in PR #54.  It does
not execute the pilot.

The approved execution identity is now:

```text
protocol: phase6_m2_formal_extension_design_v1_1
runner namespace: phase6_m2_formal_extension_v1_1
output root: outputs/phase6_m2_formal_extension_v1_1
approval: phase6_m2_formal_extension_pilot_v1_1
```

The new output root was absent when this handoff was prepared.  Results,
registry rows, and projection state from `v1_0` are not accepted by the `v1_1`
approval and must not be copied or migrated.  The old 15 mechanism runs and one
OOS probe remain immutable diagnostic evidence only.

## Scientific scope

No scientific model, scenario distribution, seed, budget, profile, strategy,
metric, or compute-gate rule changed.  The frozen pilot remains:

- three pilot training seeds;
- `beta=1.1` with `C0`, `C1`, and `T03`;
- `beta=1.3` with `C0` and `T03`;
- 15 mechanism runs in strict serial order;
- one OOS probe using training seed `2026081601`, independent test seed
  `2026081701`, five strategies, and 2,000 scenarios per strategy.

The configuration fingerprint changes because protocol, namespace, output-root
identity, and the reviewed PR #54 evidence are protected inputs.  This is an
execution-baseline revision, not a change to the mathematical experiment.

## PR #54 evidence

The configuration locks the PR #54 merge commit and the byte hash of its
machine audit.  The corrected validator requires the objective tolerance and
both endpoint differences to be finite and nonnegative and applies the
existing acceptance boundary:

```text
difference <= objective_tolerance + 1e-8
```

## Approved fingerprints

| Field | v1.1 value |
| --- | --- |
| scientific configuration | `02d50abd609acd9d93eca6b13f6195e6eee14330e3db5c5ca75e83d2e7b56612` |
| E3 component | `87f643fd3bf90f825251641c1bdeeb25f4aebb1ea23d052913b27e0b5fdf2924` |
| family component | `b1f9278ee8a0085e80c418f33d04c92b943c215eaf9ca2cdb6144e8dcebdb68b` |
| runner configuration | `c8d9efb59649b2a3e16839cdece7c38bc5a385358c354b72310c32134f49ad8e` |
| environment | `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af` |

## Stop boundary

Execution counts in this PR are all zero.  No scenario was generated and no
Gurobi call, pilot, formal extension, algorithm-performance run, or M0 E3 run
was started.  `formal_extension_authorized` remains `false` regardless of a
future successful pilot compute gate.

After review and manual merge, a separate explicit user instruction is still
required before rerunning the complete 15+1 batch with a fresh run-ID prefix.
The run must stop after projection and results evidence are finalized.

Base merge commit: `5c955f738aff8f379c0ff8bb59ac97c91a43399e`

Base tree: `e9f53836c947b361a02cf26f2418fe3a739b4b65`

The final PR head and CI are recorded in the PR description to avoid
self-reference.
