from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    ROOT
    / "docs"
    / "handoffs"
    / "2026-08-11_phase6_m1_development_grid_audit.json"
)
SUMMARY_PATH = (
    ROOT
    / "docs"
    / "handoffs"
    / "2026-08-11_phase6_m1_development_grid_projection_summary.json"
)

EXPECTED_EXECUTION = {
    "git_sha": "5c899db05ff8d004d3ca1c90bfa58e30bafe1328",
    "git_tree_sha": "f8baba05fa84ab717459065685049c4106cdc9f3",
    "working_tree_dirty_at_start": False,
    "tracked_modified_count_at_start": 0,
    "untracked_execution_input_count_at_start": 0,
    "python_version": "3.12.10",
    "solver": "gurobi_direct",
    "gurobi_optimizer_version": "13.0.2",
    "gurobipy_version": "13.0.2",
    "threads": 1,
    "strict_serial_execution": True,
}
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": (
        "6439d8a1945e44985cb1c8b20a20b7641617ed9a160db554680f3dc4680aa8c8"
    ),
    "e3_component_sha256": (
        "994e72479f0994c134d112bef1af78421ee3cca25593ab6a9d1146e153afbde2"
    ),
    "family_component_sha256": (
        "05065fba9dd69665bf556da2e6b44fde7e0f73d476172811aeb4d662b74a839d"
    ),
    "runner_config_sha256": (
        "4e39efe184877da9892e63852298bad4f9662b6d09af7ef5fedd6c4a09a13f3a"
    ),
    "environment_sha256": (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    ),
}
EXPECTED_GLOBAL_ARTIFACTS = {
    "development_run_registry_sha256": (
        "2694e0e7fdcf249f40f5e38cbfe4e9bdd3725735dce6bb1ab1faa88b099692e2"
    ),
    "development_activation_projection_sha256": (
        "005bedc92c59d16ebea2cece5302638c904d08a9f74db6d6df71c1ce8f68e8b7"
    ),
}
EXPECTED_RUN_EVIDENCE_SHA256 = (
    "59f9bf02d503fe917d785c533b140dc0260f1e2140c64cfeeb1c12bf8efc3a05"
)
EXPECTED_COMBINATION_EVIDENCE_SHA256 = (
    "65602736c6cfb6c65920b2b921cc09a930ff0e21d6548fa685899cb0d1a86621"
)
EXPECTED_SUMMARY_SHA256 = (
    "e88221b1e19509282b7ce3dbd653b957296d64178a3e3429c762975e031d8b5f"
)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _case_id(seed: int, beta: float, kappa: float | None) -> str:
    beta_token = f"{beta:.2f}".replace(".", "p")
    kappa_token = "unbounded" if kappa is None else f"{kappa:.2f}".replace(".", "p")
    return f"V1_seed{seed}_beta{beta_token}_kappa{kappa_token}"


def test_m1_development_grid_run_evidence_is_complete_and_locked() -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    runs = audit["runs"]

    assert audit["execution"] == EXPECTED_EXECUTION
    assert audit["fingerprints"] == EXPECTED_FINGERPRINTS
    assert audit["artifacts"] == EXPECTED_GLOBAL_ARTIFACTS
    assert audit["projection_summary_sha256"] == EXPECTED_SUMMARY_SHA256
    assert hashlib.sha256(SUMMARY_PATH.read_bytes()).hexdigest() == EXPECTED_SUMMARY_SHA256

    seeds = (2026081101, 2026081102, 2026081103)
    betas = (0.9, 1.1, 1.3)
    kappas = (None, 1.5, 1.3, 1.2, 1.1, 1.0, 0.8)
    expected_cases = {
        _case_id(seed, beta, kappa)
        for seed in seeds
        for beta in betas
        for kappa in kappas
    }
    actual_cases = {run["case_id"] for run in runs}
    assert actual_cases == expected_cases
    assert len(runs) == len(actual_cases) == 63

    expected_run_ids = {f"m1dev_v1_20260811_{case_id}" for case_id in expected_cases}
    assert {run["run_id"] for run in runs} == expected_run_ids
    assert audit["run_evidence_sha256"] == EXPECTED_RUN_EVIDENCE_SHA256
    assert _canonical_sha256(runs) == EXPECTED_RUN_EVIDENCE_SHA256

    for run in runs:
        assert run["parent_run_id"] is None
        assert run["tier_id"] == "V1"
        assert run["status"] == "optimal"
        assert run["finalized"] is True
        assert run["git_sha"] == EXPECTED_EXECUTION["git_sha"]
        assert run["git_tree_sha"] == EXPECTED_EXECUTION["git_tree_sha"]
        assert run["fingerprints"] == EXPECTED_FINGERPRINTS
        assert len(run["result_sha256"]) == 64
        assert len(run["manifest_sha256"]) == 64
        assert len(run["status_summary_sha256"]) == 64
        assert run["solver"] == "gurobi_direct"
        assert run["gurobi_optimizer_version"] == "13.0.2"
        assert run["gurobipy_version"] == "13.0.2"
        assert run["threads"] == 1
        assert run["memory_metric"] == "sampled_process_peak_rss_mb"
        assert run["failure_counts"] == {
            "infeasible_recourse": 0,
            "solver_failure": 0,
            "runner_failure": 0,
            "timeout": 0,
            "missing": 0,
        }
        assert run["endpoint_failure_counts"] == {
            "minimum": {"infeasible": 0, "solver_failure": 0, "missing": 0},
            "maximum": {"infeasible": 0, "solver_failure": 0, "missing": 0},
        }
        assert run["R_star"] == run["R_min_feas"]
        assert run["R_min_opt"] == run["R_min_feas"]
        assert run["R_disc_robust"] == 0.0
        assert run["R_disc_robust_ratio"] == 0.0
        assert run["numerical_activation"] is False
        assert run["substantive_activation"] is False
        assert run["minimum_endpoint_consistency_difference"] <= (
            run["objective_tolerance"] + 1.0e-8
        )
        assert run["maximum_endpoint_consistency_difference"] <= (
            run["objective_tolerance"] + 1.0e-8
        )
        policies = run["fixed_autonomous_reserve_policies"]
        assert [policy["rho"] for policy in policies] == [0.0, 0.1, 0.3, 0.5]
        assert all(policy["status"] == "optimal" for policy in policies)
        assert all(len(policy["regular_purchase_sha256"]) == 64 for policy in policies)

    counts = audit["counts"]
    assert counts == {
        "primary_run_count": 63,
        "optimal_primary_run_count": 63,
        "unique_case_id_count": 63,
        "diagnostic_run_count": 0,
        "duplicate_case_count": 0,
        "invalid_primary_run_count": 0,
        "invalid_diagnostic_run_count": 0,
        "numerical_activation_run_count": 0,
        "substantive_activation_run_count": 0,
        "fixed_policy_solve_count": 252,
    }
    assert all(value == 0 for value in audit["failure_totals"].values())
    assert all(
        value == 0
        for endpoint in audit["endpoint_failure_totals"].values()
        for value in endpoint.values()
    )
    assert audit["numerical_summary"]["max_abs_R_star_minus_R_min_feas"] == 0.0
    assert audit["numerical_summary"]["max_abs_R_min_opt_minus_R_min_feas"] == 0.0
    assert audit["numerical_summary"]["max_R_disc_robust_ratio"] == 0.0


def test_m1_development_projection_recomputes_the_preregistered_gate() -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    combinations = summary["combinations"]

    assert summary["execution"] == EXPECTED_EXECUTION
    assert summary["fingerprints"] == EXPECTED_FINGERPRINTS
    assert summary["artifacts"] == EXPECTED_GLOBAL_ARTIFACTS
    assert len(combinations) == summary["combination_count"] == 21
    assert summary["combination_evidence_sha256"] == (
        EXPECTED_COMBINATION_EVIDENCE_SHA256
    )
    assert _canonical_sha256(combinations) == EXPECTED_COMBINATION_EVIDENCE_SHA256

    expected_pairs = {
        (beta, kappa)
        for beta in (0.9, 1.1, 1.3)
        for kappa in (None, 1.5, 1.3, 1.2, 1.1, 1.0, 0.8)
    }
    assert {(row["beta"], row["kappa"]) for row in combinations} == expected_pairs
    for row in combinations:
        assert row["completed_seed_count"] == 3
        assert row["optimal_seed_count"] == 3
        assert row["substantive_activation_seed_count"] == 0
        expected_gate = (
            row["optimal_seed_count"] == 3
            and row["substantive_activation_seed_count"] >= 2
        )
        assert row["gate_passed"] is expected_gate is False
        assert len(row["run_ids"]) == 3

    assert summary["required_primary_run_count"] == 63
    assert summary["verified_primary_run_count"] == 63
    for field in (
        "missing_case_ids",
        "invalid_primary_run_ids",
        "invalid_diagnostic_run_ids",
        "duplicate_case_ids",
        "diagnostic_run_ids",
        "passed_combinations",
    ):
        assert summary[field] == []
    assert summary["projection_status"] == "completed_no_activation"
    assert summary["development_activation_gate_passed"] is False
    assert summary["formal_extension_authorized"] is False
    assert summary["stop_reason"] == "no_preregistered_combination_passed"
    assert summary["selection_metrics_excluded"] == [
        "cost",
        "service_level",
        "P95",
        "CVaR",
        "manual_trend",
    ]
    assert audit["conclusion"] == {
        "passed_combinations": [],
        "development_activation_gate_passed": False,
        "formal_extension_authorized": False,
        "stop_reason": "no_preregistered_combination_passed",
        "M1_extension_must_stop": True,
        "parameter_chasing_forbidden": True,
    }
