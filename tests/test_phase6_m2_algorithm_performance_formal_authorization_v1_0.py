from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.phase6_m2_algorithm_performance_formal import (
    PILOT_AUDIT_SHA256, build_formal_cases, formal_fingerprints,
    validate_static_freeze,
)
from src.reproducibility import sha256_file


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "configs/phase6_m2_algorithm_performance_formal_runner_v1_1.yaml"
APPROVAL = ROOT / "configs/phase6_m2_algorithm_performance_formal_approval_v1_1.yaml"
AUDIT = ROOT / "docs/handoffs/2026-08-25_phase6_m2_algorithm_performance_formal_runner_v1_1_audit.json"


def test_authorization_binds_reviewed_runner_and_all_execution_artifacts() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    assert approval["status"] == "frozen_for_formal_algorithm_performance_execution"
    assert approval["formal_authorized"] is True
    assert approval["reviewed_runner_commit"] == audit["reviewed_runner"]["commit"]
    # GitHub Actions checks out a shallow synthetic merge and may not contain
    # the intermediate reviewed commit object.  Its immutable commit/tree IDs
    # are therefore locked directly, while every executable byte is rehashed
    # below from the checkout.
    assert audit["reviewed_runner"] == {
        "commit": "1e855af3936cc19c6a6ab75a7b59efcf357a85b2",
        "tree": "ec3f82e8a33c2065259e0c415812f1dac13f4eb7",
    }
    paths = {
        "approval": APPROVAL,
        "runner_config": RUNNER,
        "orchestrator_module": ROOT / "src/phase6_m2_algorithm_performance_formal.py",
        "worker_module": ROOT / "src/phase6_m2_algorithm_performance_worker.py",
        "cli": ROOT / "src/run_phase6_m2_algorithm_performance_formal.py",
        "status_module": ROOT / "src/phase6_m2_algorithm_performance_formal_status.py",
    }
    assert {name: sha256_file(path) for name, path in paths.items()} == audit["artifact_sha256"]
    assert approval["artifact_sha256"] == {
        name: audit["artifact_sha256"][name] for name in paths if name != "approval"
    }


def test_fingerprints_matrix_and_scope_are_exact() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    context = validate_static_freeze(ROOT, RUNNER, APPROVAL)
    actual = formal_fingerprints(ROOT, RUNNER)
    # The reviewed experiment-machine environment is intentionally stricter
    # than the Linux CI environment.  Runtime preflight compares all six
    # values; CI independently rehashes the five platform-independent values.
    assert audit["fingerprints"]["environment_sha256"] == (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    )
    assert {
        key: value for key, value in actual.items() if key != "environment_sha256"
    } == {
        key: value for key, value in audit["fingerprints"].items()
        if key != "environment_sha256"
    }
    assert approval["approved_fingerprints"] == audit["fingerprints"]
    assert len(build_formal_cases(context["design"])) == 20
    assert audit["matrix"] == {
        "primary_sequence_count": 20,
        "budget_pair_count": 40,
        "algorithm_execution_count": 240,
        "technical_repetitions_per_algorithm_budget": 3,
        "scenario_count": 100,
    }
    assert audit["statistical_protocol"] == {
        "independent_unit": "formal_performance_seed",
        "technical_repetitions_reduced_by": "median",
        "primary_estimand": "T03_beta_1_3_cross_budget_transfer_speedup",
        "confirmatory_estimand": "paired_T03_vs_C0_beta_1_3_speedup_ratio",
        "secondary_end_to_end_formula": "sum_two_budget_cold_medians_divided_by_sum_two_budget_warm_medians",
        "random_number_generator": "numpy_Generator_PCG64DXSM",
        "random_seed": 2026091299, "resamples": 10000,
        "confidence_level": 0.95, "interval": "percentile_linear",
        "effect_direction_does_not_control_execution_completeness_gate": True,
    }
    authorization = audit["authorization"]
    assert authorization["formal_authorized"] is True
    assert authorization["explicit_cli_authorization_required"] is True
    assert all(
        authorization[field] is False
        for field in (
            "pilot_additional_runs_authorized", "M0_E3_additional_runs_authorized",
            "M2_mechanism_additional_runs_authorized", "M2_OOS_additional_runs_authorized",
            "M2_1_additional_runs_authorized",
        )
    )


def test_reviewed_pilot_evidence_and_zero_execution_are_locked() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    evidence = audit["reviewed_pilot_evidence"]
    pilot_path = ROOT / evidence["audit_path"]
    assert sha256_file(pilot_path) == PILOT_AUDIT_SHA256 == evidence["audit_sha256"]
    pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
    assert pilot["aggregate"]["pilot_compute_gate_passed"] is True
    assert pilot["aggregate"]["formal_authorized"] is False
    assert audit["execution_counts_in_this_pr"] == {
        "scenario_generation_count": 0,
        "gurobi_call_count": 0,
        "algorithm_performance_runs": 0,
    }
    output_root = ROOT / audit["output_root"]
    assert not output_root.exists() or not any(output_root.iterdir())
    assert audit["safety"] == {
        "old_namespace": "phase6_m2_algorithm_performance_formal_v1_0",
        "old_output_preserved_and_excluded": True,
        "new_namespace": "phase6_m2_algorithm_performance_formal_v1_1",
        "new_output_root_must_start_empty": True,
        "old_primary_results_migrated": 0,
    }
    normalization = audit["gap_evidence_normalization"]
    assert normalization == {
        "numerical_protection": 1.0e-9,
        "reject_below": -1.0e-9,
        "accepted_negative_interval": "[-1e-9,0)",
        "preserve_reported_gap": True,
        "machine_accepted_gap_for_negative_interval": 0.0,
        "reported_gap_must_match_upper_minus_lower_within": 1.0e-9,
        "nonfinite_values_rejected": True,
        "scientific_objective_tolerance_used_for_gap_normalization": False,
    }
    failure_evidence = audit["reviewed_failure_evidence"]
    failure_path = ROOT / failure_evidence["audit_path"]
    assert sha256_file(failure_path) == failure_evidence["audit_sha256"]
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    assert failure["status"] == failure_evidence["status"] == (
        "stopped_after_first_invalid_primary"
    )
    assert failure["batch_closure"]["formal_algorithm_performance_gate_passed"] is False
    assert failure["failed_primary"]["reported_gap"] == -1.4551915228366852e-11
