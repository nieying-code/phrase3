# Phase 6 M2 Development Grid Handoff

## Scope

The frozen M2 V1 development grid was executed once from merged PR #44. It contains three development seeds, three budget factors, and the preregistered C0/C1/C2 disruption profiles: `3 × 3 × 3 = 27` primary runs. Runs were strictly serial and used Gurobi/gurobipy 13.0.2 through `gurobi_direct` with `Threads=1`.

No M0 E3, pilot, formal extension, or multi-item confirmation experiment was started.

## Execution identity

- Branch: `results/phase6-m2-development-grid-v1-1`
- Results evidence commit: `98fabff`
- CI-validated audit head: `eace428`
- Draft PR: https://github.com/nieying-code/phrase3/pull/45
- Source commit: `2cdb09bd887bc8887ab956a0a0281d7c30170a40`
- Source tree: `8a3a6865e56b8214160ac97e0958041025a89ee0`
- Run prefix: `m2dev_v1_1_20260813`
- Output root: `outputs/phase6_m2_supply_disruption_v1_1`
- Worktree at start: clean; zero untracked execution inputs
- Scientific/runner/environment identities: locked in the machine audit

## Results

- Primary runs: `27/27 optimal`
- Missing, invalid, duplicate, diagnostic, timeout, recourse-infeasible, and solver-failure records: `0`
- Endpoint exact-recourse evaluations: all optimal and within each run's frozen objective tolerance
- Fixed autonomous-reserve policies: four per run; all reoptimized and optimal
- Common-random-number checks: passed for every seed–budget C0/C1/C2 triplet
- Total runner wall time: approximately `177.79 s`
- Maximum sampled RSS: approximately `102.64 MB`

The preregistered activation gate passed only for the severe-disruption profile C2:

| beta | profile | optimal seeds | substantive activation | gate |
|---:|:---:|---:|---:|:---:|
| 0.9 | C2 | 3/3 | 3/3 | passed |
| 1.1 | C2 | 3/3 | 3/3 | passed |
| 1.3 | C2 | 3/3 | 3/3 | passed |

C0 was optimal for 3/3 seeds at every budget and had zero substantive activation. C1 likewise had zero activation. This supports a disruption-dependent activation boundary within the preregistered V1 development grid.

## Interpretation boundary

The C2 autonomous-reserve ratios are very high (roughly 0.905 to almost 1.0). This is valid development evidence that the mechanism activates, but it is not yet a formal empirical conclusion and should not be interpreted as a calibrated policy recommendation. The next scientific decision requires separate review; this run does not authorize a multi-item confirmation or a formal extension experiment.

## Artifacts

- Compact machine audit: `docs/handoffs/2026-08-13_phase6_m2_development_grid_audit.json`
- Projection summary: `docs/handoffs/2026-08-13_phase6_m2_development_grid_projection_summary.json`
- Raw artifacts remain on the D drive and are not committed.
- CI: [run 31662287525](https://github.com/nieying-code/phrase3/actions/runs/31662287525), Linux and Windows passed

## Stop boundary

`development_activation_gate_passed=true` and `formal_extension_authorized=false`. Work stops here for independent review. No automatic parameter selection, multi-item confirmation, or formal experiment is permitted.
