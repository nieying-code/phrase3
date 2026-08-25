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
RUNNER = ROOT / "configs/phase6_m2_algorithm_performance_formal_runner_v1_0.yaml"
APPROVAL = ROOT / "configs/phase6_m2_algorithm_performance_formal_approval_v1_0.yaml"
AUDIT = ROOT / "docs/handoffs/2026-08-25_phase6_m2_algorithm_performance_formal_runner_v1_0_audit.json"


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
        "commit": "794856b7b50e1c118b6ec8b56b34c4c30f752225",
        "tree": "5f896aa32a7d1f5b1ee3e68f0f1b879f4ab54ce6",
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
