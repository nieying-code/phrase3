from __future__ import annotations

import json
from pathlib import Path

from src.phase6_m0_algorithm_performance import (
    _sha256_lf_text,
    algorithm_performance_orchestrator_sha256,
    build_performance_cases,
)
from src.phase6_protocol import load_phase6_matrix
from src.reproducibility import sha256_file


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "docs/handoffs/2026-08-23_phase6_m0_algorithm_performance_runner_v1_0_audit.json"


def _audit() -> dict:
    return json.loads(AUDIT_PATH.read_text(encoding="utf-8"))


def test_audit_recomputes_the_complete_frozen_matrix():
    audit = _audit()
    matrix_path = ROOT / "configs/phase6_experiment_matrix.yaml"
    matrix = load_phase6_matrix(matrix_path)
    cases = build_performance_cases(matrix)
    assert sha256_file(matrix_path) == audit["matrix"]["matrix_sha256"]
    assert len(cases) == audit["matrix"]["primary_run_count"] == 21
    assert 3 * len(cases) == audit["matrix"]["budget_pair_count"] == 63
    assert sum(row.algorithm_execution_count for row in cases) == audit["matrix"]["algorithm_execution_count"] == 246
    for tier_id, expected in audit["matrix"]["tiers"].items():
        tier_cases = [row for row in cases if row.tier_id == tier_id]
        assert len(tier_cases) == expected["formal_seed_count"]
        assert {row.timing_repetitions for row in tier_cases} == {expected["timing_repetitions"]}
        assert sum(row.algorithm_execution_count for row in tier_cases) == expected["algorithm_execution_count"]


def test_audit_locks_reviewed_projection_and_e1_evidence():
    audit = _audit()
    evidence = audit["reviewed_evidence"]
    assert _sha256_lf_text(ROOT / evidence["final_projection_audit_path"]) == evidence["final_projection_audit_sha256"]
    assert _sha256_lf_text(ROOT / evidence["E1_formal_audit_path"]) == evidence["E1_formal_audit_sha256"]
    projection = json.loads((ROOT / evidence["final_projection_audit_path"]).read_text(encoding="utf-8"))
    e1 = json.loads((ROOT / evidence["E1_formal_audit_path"]).read_text(encoding="utf-8"))
    assert projection["e3_gate_inputs"]["completed_run_count"] == projection["e3_gate_inputs"]["required_run_count"] == 12
    assert projection["compute_gate"]["compute_gate_passed"] is True
    assert projection["compute_gate"]["formal_execution_authorized"] is True
    assert e1["counts"]["primary_run_count"] == e1["counts"]["optimal_primary_run_count"] == 14
    assert e1["counts"]["completed_work_unit_count"] == e1["counts"]["planned_work_unit_count"] == 45
    assert e1["numerical_consistency"]["all_objective_differences_within_plan_tolerance"] is True


def test_audit_artifact_and_orchestrator_hashes_are_independently_recomputed():
    audit = _audit()
    paths = {
        "runner_config": "configs/phase6_m0_algorithm_performance_runner.yaml",
        "approval": "configs/phase6_m0_algorithm_performance_approval_v1_0.yaml",
        "orchestrator_module": "src/phase6_m0_algorithm_performance.py",
        "cli": "src/run_phase6_m0_algorithm_performance.py",
        "status_module": "src/phase6_m0_algorithm_performance_status.py",
    }
    for field, relative in paths.items():
        assert sha256_file(ROOT / relative) == audit["artifact_sha256"][field]
    assert algorithm_performance_orchestrator_sha256(ROOT) == audit["fingerprints"]["algorithm_performance_orchestrator_sha256"]


def test_audit_authorization_and_zero_execution_boundary_are_exact():
    audit = _audit()
    assert audit["authorizations"] == {
        "M0_E3_algorithm_performance_authorized": True,
        "M2_formal_authorized": False,
        "M2_formal_OOS_authorized": False,
        "M2_1_authorized": False,
        "other_formal_experiments_authorized": False,
    }
    assert audit["execution_counts_in_this_revision"] == {
        "scenario_generation_count": 0,
        "gurobi_call_count": 0,
        "algorithm_performance_runs": 0,
        "M2_performance_runs": 0,
        "M2_1_runs": 0,
    }
    assert audit["scientific_roles"]["V2_technical_repetitions_are_independent_samples"] is False
    assert audit["scientific_roles"]["M2_speed_comparison_in_scope"] is False
    assert not (ROOT / "outputs/phase6_m0_e3_algorithm_performance_v1_0").exists()
