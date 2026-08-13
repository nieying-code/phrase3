# Phase 6 M2 Threshold-Refinement Runner

This runner executes only the frozen 27-case V1 refinement matrix. It has an independent namespace and output root and never imports the parent M2 registry or projection. Approved C1/C2 evidence is read from the committed compact audit after its file hash is verified.

Execution requires both `status=frozen_for_development_execution` and the explicit CLI flag:

```powershell
.venv-gurobi\Scripts\python.exe -m src.run_phase6_m2_threshold_refinement `
  --config configs/phase6_m2_threshold_refinement.yaml `
  --runner-config configs/phase6_m2_threshold_refinement_runner.yaml `
  --approval configs/phase6_m2_threshold_refinement_approval.yaml `
  --run-id-prefix m2refine_v1_YYYYMMDD `
  --authorize-development-execution
```

The runner executes strictly by seed, beta, then T03/T04/T05. Every run ID is immutable, failures stop later cases, and diagnostic retries require a new run ID and `parent_run_id`. Status monitoring reads only bounded `status_summary.json` or the compact projection.

Projection independently recomputes activation from `R_min_opt`, `R_min_feas`, and budget. It verifies endpoint recourse, fixed-policy reoptimization, common-random-number component hashes, per-beta monotone binary activation, and the conjunctive moderate gate. It can never authorize formal extension execution.

This implementation PR does not run the matrix, generate scenarios, or call Gurobi.
