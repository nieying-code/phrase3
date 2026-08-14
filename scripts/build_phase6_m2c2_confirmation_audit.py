"""Build the compact, deterministic audit for finalized M2C2 confirmation runs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from src.phase6_io import atomic_write_json
from src.phase6_m2 import _sha256_payload
from src.phase6_m2c2_confirmation import _validate_artifact
from src.reproducibility import sha256_file


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "outputs/phase6_m2c2_confirmation_v1_0"
CONFIRMATION_ROOT = OUTPUT_ROOT / "confirmation"
AUDIT_PATH = ROOT / "docs/handoffs/2026-08-14_phase6_m2c2_confirmation_grid_audit.json"


def _read_registry() -> list[dict[str, str]]:
    with (CONFIRMATION_ROOT / "confirmation_run_registry.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        return list(csv.DictReader(handle))


def _compact_run(row: dict[str, str]) -> dict[str, Any]:
    result = _validate_artifact(OUTPUT_ROOT, row)
    science = result["science"]
    directory = Path(row["result_path"]).parent
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    source = manifest["source"]
    cross = science["cross_item_allocation"]
    return {
        "run_id": result["run_id"],
        "parent_run_id": result["parent_run_id"],
        "case_id": result["case_id"],
        "tier_id": science["tier_id"],
        "seed": science["seed"],
        "beta": science["beta"],
        "profile_id": science["profile_id"],
        "status": result["status"],
        "git_sha": result["git_sha"],
        "git_tree_sha": result["git_tree_sha"],
        "source_working_tree_dirty": source["working_tree_dirty"],
        "untracked_execution_input_count_at_start": len(
            source["untracked_execution_input_paths"]
        ),
        "fingerprints": result["fingerprints"],
        "artifacts": {
            "result_sha256": sha256_file(directory / "result.json"),
            "manifest_sha256": sha256_file(directory / "manifest.json"),
            "checkpoint_sha256": sha256_file(directory / "checkpoint.json"),
            "status_summary_sha256": sha256_file(directory / "status_summary.json"),
            "heartbeat_sha256": sha256_file(directory / "heartbeat.json"),
        },
        "reference_budget": science["reference_budget"],
        "budget": science["budget"],
        "storage_capacity": science["storage_capacity"],
        "R_star": science["R_star"],
        "R_min_feas": science["R_min_feas"],
        "R_min_opt": science["R_min_opt"],
        "R_max_opt": science["R_max_opt"],
        "R_disc_robust": science["R_min_robust_opt"],
        "R_disc_robust_ratio": science["R_min_robust_opt_ratio"],
        "numerical_activation": science["numerical_activation"],
        "substantive_activation": science["substantive_activation"],
        "moderate_activation": science["moderate_activation"],
        "complete_extensive_objective": science["complete_extensive_objective"],
        "objective_tolerance": science["objective_tolerance"],
        "minimum_endpoint_status": science["minimum_endpoint_status"],
        "maximum_endpoint_status": science["maximum_endpoint_status"],
        "minimum_endpoint_exact_objective": science["minimum_endpoint_exact_objective"],
        "maximum_endpoint_exact_objective": science["maximum_endpoint_exact_objective"],
        "minimum_endpoint_consistency_difference": science["minimum_endpoint_consistency_difference"],
        "maximum_endpoint_consistency_difference": science["maximum_endpoint_consistency_difference"],
        "minimum_endpoint_regular_purchase_sha256": science["minimum_endpoint_regular_purchase_sha256"],
        "maximum_endpoint_regular_purchase_sha256": science["maximum_endpoint_regular_purchase_sha256"],
        "endpoint_failure_counts": science["endpoint_failure_counts"],
        "fixed_reserve_policies": science["fixed_reserve_policies"],
        "fulfillment_statistics": science["fulfillment_statistics"],
        "joint_scenario_set_sha256": science["joint_scenario_set_sha256"],
        "scenario_component_set_sha256": science["scenario_component_set_sha256"],
        "scenario_identity_count": science["scenario_identity_count"],
        "cross_item_allocation": {
            key: cross[key]
            for key in (
                "plan_source", "endpoint_reserve",
                "endpoint_regular_purchase_sha256", "endpoint_exact_objective",
                "scenario_count", "scenario_item_emergency_spend_sha256",
                "positive_total_emergency_spend_scenario_count",
                "both_items_each_positive_in_at_least_one_scenario",
                "item1_emergency_spend_share_range", "gate_passed",
            )
        },
        "c0_equivalence": science["c0_equivalence"],
        "solver": science["solver"],
        "gurobi_optimizer_version": science["gurobi_optimizer_version"],
        "gurobipy_version": science["gurobipy_version"],
        "threads": science["threads"],
        "wall_seconds": result["wall_seconds"],
        "peak_memory_mb": result["peak_memory_mb"],
    }


def build_audit() -> dict[str, Any]:
    rows = _read_registry()
    if len(rows) != 30:
        raise RuntimeError("M2C2 audit requires exactly 30 registry rows")
    runs = [_compact_run(row) for row in rows]
    projection_path = CONFIRMATION_ROOT / "confirmation_projection.json"
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    if projection.get("status") != "complete" or projection.get("verified_primary_run_count") != 30:
        raise RuntimeError("M2C2 projection is not complete")
    artifact_mapping = {row["run_id"]: row["artifacts"] for row in runs}
    science_fields = (
        "case_id", "seed", "beta", "profile_id", "budget", "R_star",
        "R_min_feas", "R_min_opt", "R_max_opt", "R_disc_robust",
        "R_disc_robust_ratio", "numerical_activation",
        "substantive_activation", "moderate_activation",
        "joint_scenario_set_sha256",
    )
    science_mapping = {
        row["run_id"]: {field: row[field] for field in science_fields}
        for row in runs
    }
    return {
        "audit_id": "phase6_m2c2_confirmation_grid_v1_0",
        "status": "confirmation_grid_complete_pending_review",
        "execution": {
            "branch": "results/phase6-m2c2-confirmation-grid",
            "run_id_prefix": "m2c2_confirm_v1_20260814",
            "git_sha": runs[0]["git_sha"],
            "git_tree_sha": runs[0]["git_tree_sha"],
            "working_tree_dirty": any(
                row["source_working_tree_dirty"] for row in runs
            ),
            "untracked_execution_input_count_at_start": sum(
                row["untracked_execution_input_count_at_start"] for row in runs
            ),
            "strictly_serial": True,
        },
        "fingerprints": runs[0]["fingerprints"],
        "matrix": {
            "tier_id": "M2C2",
            "seeds": [2026081301, 2026081302, 2026081303, 2026081304, 2026081305],
            "betas": [1.1, 1.3],
            "profiles": ["C0", "C1", "T03"],
            "case_count": 30,
            "reference_budget": 2337.610924158743,
        },
        "runs": runs,
        "mapping_hashes": {
            "run_artifact_mapping_sha256": _sha256_payload(artifact_mapping),
            "science_evidence_mapping_sha256": _sha256_payload(science_mapping),
        },
        "aggregate": {
            "optimal_run_count": sum(row["status"] == "optimal" for row in runs),
            "numerical_activation_run_count": sum(row["numerical_activation"] for row in runs),
            "substantive_activation_run_count": sum(row["substantive_activation"] for row in runs),
            "moderate_activation_run_count": sum(row["moderate_activation"] for row in runs),
            "max_R_disc_robust_ratio": max(row["R_disc_robust_ratio"] for row in runs),
            "max_endpoint_consistency_difference": max(
                max(abs(row["minimum_endpoint_consistency_difference"]), abs(row["maximum_endpoint_consistency_difference"]))
                for row in runs
            ),
            "total_wall_seconds": sum(row["wall_seconds"] for row in runs),
            "peak_memory_mb": max(row["peak_memory_mb"] for row in runs),
        },
        "projection": projection,
        "global_artifacts": {
            "registry_sha256": sha256_file(CONFIRMATION_ROOT / "confirmation_run_registry.csv"),
            "projection_sha256": sha256_file(projection_path),
        },
        "execution_boundaries": {
            "M2C2_confirmation_runs": 30,
            "diagnostic_runs": 0,
            "pilot_runs": 0,
            "formal_extension_runs": 0,
            "M0_E3_runs": 0,
        },
        "formal_extension_authorized": False,
    }


def main() -> int:
    atomic_write_json(AUDIT_PATH, build_audit())
    print(AUDIT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
