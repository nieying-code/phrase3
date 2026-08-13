"""Generate the compact, reviewable audit for the completed M2 refinement grid."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "outputs/phase6_m2_threshold_refinement_v1_0/development"
RUNS = BASE / "runs"
DOCS = ROOT / "docs/handoffs"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


projection = json.loads((BASE / "threshold_refinement_projection.json").read_text(encoding="utf-8"))
registry = list(csv.DictReader((BASE / "refinement_run_registry.csv").open(encoding="utf-8-sig", newline="")))
runs = []
for row in registry:
    result_path = Path(row["result_path"])
    manifest_path = Path(row["manifest_path"])
    result = json.loads(result_path.read_text(encoding="utf-8"))
    science = result["science"]
    run_dir = result_path.parent
    runs.append({
        "run_id": result["run_id"], "case_id": result["case_id"],
        "tier_id": science["tier_id"], "seed": science["seed"],
        "beta": science["beta"], "profile_id": science["profile_id"],
        "status": result["status"], "parent_run_id": result["parent_run_id"],
        "git_sha": result["git_sha"], "git_tree_sha": result["git_tree_sha"],
        "fingerprints": result["fingerprints"],
        "artifacts": {
            "result_sha256": sha(result_path), "manifest_sha256": sha(manifest_path),
            "status_summary_sha256": sha(run_dir / "status_summary.json"),
            "heartbeat_sha256": sha(run_dir / "heartbeat.json"),
        },
        "budget": science["budget"], "reference_budget": science["reference_budget"],
        "R_star": science["R_star"], "R_min_feas": science["R_min_feas"],
        "R_min_opt": science["R_min_opt"], "R_max_opt": science["R_max_opt"],
        "R_disc_robust": science["R_min_robust_opt"],
        "R_disc_robust_ratio": science["R_min_robust_opt_ratio"],
        "numerical_activation": science["numerical_activation"],
        "substantive_activation": science["substantive_activation"],
        "objective_tolerance": science["objective_tolerance"],
        "complete_extensive_objective": science["complete_extensive_objective"],
        "minimum_endpoint_status": science["minimum_endpoint_status"],
        "maximum_endpoint_status": science["maximum_endpoint_status"],
        "minimum_endpoint_consistency_difference": science["minimum_endpoint_consistency_difference"],
        "maximum_endpoint_consistency_difference": science["maximum_endpoint_consistency_difference"],
        "endpoint_failure_counts": science["endpoint_failure_counts"],
        "fixed_reserve_policies": [{
            "rho": item["rho"], "reserve": item["reserve"], "status": item["status"],
            "regular_purchase_reoptimized": item["regular_purchase_reoptimized"],
            "regular_purchase_sha256": item["regular_purchase_sha256"],
        } for item in science["fixed_reserve_policies"]],
        "joint_scenario_set_sha256": science["joint_scenario_set_sha256"],
        "scenario_component_set_sha256": science["scenario_component_set_sha256"],
        "scenario_identity_count": science["scenario_identity_count"],
        "solver": science["solver"], "gurobi_optimizer_version": science["gurobi_optimizer_version"],
        "gurobipy_version": science["gurobipy_version"], "threads": science["threads"],
        "wall_seconds": result["wall_seconds"], "peak_memory_mb": result["peak_memory_mb"],
    })
runs.sort(key=lambda item: (item["seed"], item["beta"], item["profile_id"]))

artifact_mapping = {row["run_id"]: row["artifacts"] for row in runs}
science_fields = ("case_id", "seed", "beta", "profile_id", "budget", "R_star", "R_min_feas", "R_min_opt", "R_max_opt", "R_disc_robust", "R_disc_robust_ratio", "numerical_activation", "substantive_activation", "joint_scenario_set_sha256")
science_mapping = {row["run_id"]: {field: row[field] for field in science_fields} for row in runs}
audit = {
    "audit_id": "phase6_m2_threshold_refinement_v1_0_development_grid_v1",
    "status": "development_grid_complete_pending_review",
    "execution": {
        "branch": "results/phase6-m2-threshold-refinement",
        "run_id_prefix": "m2refine_v1_20260813",
        "git_sha": runs[0]["git_sha"], "git_tree_sha": runs[0]["git_tree_sha"],
        "working_tree_dirty": False, "untracked_execution_input_count_at_start": 0,
        "strictly_serial": True,
    },
    "design": {"tier_id": "V1", "seeds": [2026081201, 2026081202, 2026081203], "betas": [0.9, 1.1, 1.3], "profiles": ["T03", "T04", "T05"], "required_case_count": 27, "numerical_activation_threshold": 1e-4, "substantive_activation_threshold": 0.01, "moderate_interval": [0.05, 0.5]},
    "fingerprints": projection["fingerprints"], "runs": runs,
    "parent_evidence": {
        "audit_path": "docs/handoffs/2026-08-13_phase6_m2_development_grid_audit.json",
        "audit_sha256": "01e3025566c0701f41b4fde6b51d1e13347068e8b8c025873c2578cfbdb349a2",
        "draft_pr": "https://github.com/nieying-code/phrase3/pull/45",
        "run_artifact_mapping_sha256": "5e8dedaf26113bf1602bcf9813265a77990b734540e25a2bef314a9940b6275a",
        "science_evidence_mapping_sha256": "619c40b858ca32728f33b2cccb32df150ef957307ab9d62840ab0037f285c4b0",
        "C1_record_count": 9, "C2_record_count": 9,
    },
    "mapping_hashes": {"run_artifact_mapping_sha256": canonical(artifact_mapping), "science_evidence_mapping_sha256": canonical(science_mapping)},
    "global_artifacts": {"registry_sha256": sha(BASE / "refinement_run_registry.csv"), "projection_sha256": sha(BASE / "threshold_refinement_projection.json")},
    "projection": projection,
    "aggregate": {
        "optimal_run_count": sum(row["status"] == "optimal" for row in runs),
        "numerical_activation_run_count": sum(row["numerical_activation"] for row in runs),
        "substantive_activation_run_count": sum(row["substantive_activation"] for row in runs),
        "max_R_disc_robust_ratio": max(row["R_disc_robust_ratio"] for row in runs),
        "max_endpoint_consistency_difference": max(max(abs(row["minimum_endpoint_consistency_difference"]), abs(row["maximum_endpoint_consistency_difference"])) for row in runs),
        "total_wall_seconds": sum(row["wall_seconds"] for row in runs),
        "peak_memory_mb": max(row["peak_memory_mb"] for row in runs),
    },
    "execution_boundaries": {"refinement_development_runs": 27, "diagnostic_runs": 0, "pilot_runs": 0, "formal_extension_runs": 0, "multi_item_confirmation_runs": 0, "M0_E3_runs": 0},
    "validation": {"specialized_passed": 19, "complete_regression_passed": 309, "phase5_passed": 6, "compileall_passed": True, "git_diff_check_passed": True},
    "formal_extension_authorized": False,
    "draft_pr": "pending", "github_actions": "pending",
}
(DOCS / "2026-08-13_phase6_m2_threshold_refinement_grid_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
(DOCS / "2026-08-13_phase6_m2_threshold_refinement_projection_summary.json").write_text(json.dumps({"audit_id": audit["audit_id"], "fingerprints": projection["fingerprints"], "combinations": projection["combinations"], "beta_assessments": projection["beta_assessments"], "eligible_moderate_combinations": projection["eligible_moderate_combinations"], "overall_decision": projection["overall_decision"], "development_activation_gate_passed": projection["development_activation_gate_passed"], "moderate_activation_gate_passed": projection["moderate_activation_gate_passed"], "formal_extension_authorized": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
