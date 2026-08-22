from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import pytest
import yaml

import src.phase6_m2_1_pilot as pilot
import src.run_phase6_m2_1_pilot as cli
from src.phase6_m2_1_pilot_status import MAX_BYTES, read_status


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / pilot.PILOT_CONFIG_PATH
RUNNER = ROOT / pilot.RUNNER_CONFIG_PATH
APPROVAL = ROOT / pilot.APPROVAL_PATH
DESIGN = ROOT / pilot.DESIGN_CONFIG_PATH
AUDIT = ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_pilot_runner_v1_0_audit.json"
SHA = "a" * 64
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": "91e20926b71287e61ea0adcd95c4f6c2f67c452c678c2a7bd380c02c27515c71",
    "e3_component_sha256": "ec5545db03791d053b14942fa02f94215a2d3711634c90a747fec6e9e5dfe618",
    "family_component_sha256": "3807bffa3e301656a818a80a5942439ed6bd1b2ece9812b47be661b29758f071",
    "runner_config_sha256": "b0f975506ac5de4262987f40bbee50af60b9343730fff9a37139dc7068ed8bc2",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}


def _configs():
    return pilot.load_pilot_config(CONFIG), pilot.load_m2_1_config(DESIGN)


def _fingerprints() -> dict[str, str]:
    return {field: hashlib.sha256(field.encode()).hexdigest() for field in pilot.FINGERPRINT_FIELDS}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_runner_artifacts_parent_evidence_and_fingerprints_are_locked() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["base"] == {
        "pr62_merge_commit": "770c863d69ba37ba858b00931310f94a9fb84e77",
        "pr62_merge_tree": "043de6a433376928e9544c6e2d7784811a37a7d2",
        "branch": "agent/phase6-m2-1-pilot-runner",
    }
    artifacts = {
        "pilot_config": (CONFIG, "f593c2469ee88ba49098e96c2e42354af74ae7f0d8cea59d15a3d1f8b4aa8fbf"),
        "runner_config": (RUNNER, "b0f975506ac5de4262987f40bbee50af60b9343730fff9a37139dc7068ed8bc2"),
        "approval": (APPROVAL, "8920e27bf392f9dbdb113352b8610c15290f42b1bfb6f9085c21b570854d4d2b"),
        "runner_module": (ROOT / "src/phase6_m2_1_pilot.py", "e912c4b630a279fadb368a3e62244d77f30cd730edc4d996ac05c567f104138c"),
        "cli": (ROOT / "src/run_phase6_m2_1_pilot.py", "415759c084400c256440a9634ac10b54b98d829ec01a0ba32140831cce7609c7"),
        "status_module": (ROOT / "src/phase6_m2_1_pilot_status.py", "e913f26a12890ea192bfd6ce292f948b990c53464d6005a4c87da35a167b20a3"),
    }
    assert audit["artifact_sha256"] == {name: expected for name, (_, expected) in artifacts.items()}
    for path, expected in artifacts.values():
        assert _sha256(path) == expected
    assert audit["parent_evidence"] == {
        "design_config_sha256": _sha256(DESIGN),
        "pr62_audit_sha256": _sha256(ROOT / "docs/handoffs/2026-08-21_phase6_m2_1_endpoint_selection_design_v1_0_audit.json"),
        "formal_extension_config_sha256": _sha256(ROOT / pilot.FORMAL_BASE_CONFIG_PATH),
        "confirmation_config_sha256": _sha256(ROOT / "configs/phase6_m2_two_item_confirmation.yaml"),
    }
    actual = pilot.pilot_fingerprints(ROOT, CONFIG, RUNNER)
    for field in (
        "scientific_config_sha256", "e3_component_sha256",
        "family_component_sha256", "runner_config_sha256",
    ):
        assert actual[field] == EXPECTED_FINGERPRINTS[field]
    # CI hardware is intentionally different from the approved experiment
    # machine.  Actual pilot preflight still compares all five fields against
    # approval and therefore cannot run on CI or a different workstation.
    assert len(actual["environment_sha256"]) == 64
    assert yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))["approved_fingerprints"] == EXPECTED_FINGERPRINTS
    assert audit["fingerprints"] == EXPECTED_FINGERPRINTS


def _scenario_identity(fill: str = "a") -> dict[str, str]:
    return {field: fill * 64 for field in pilot.SCENARIO_IDENTITY_FIELDS}


def _plan_identity(strategy: str, index: int) -> dict:
    return {
        "strategy_id": strategy,
        "path": f"plans/{strategy}.json",
        "finalized_plan_artifact_sha256": hashlib.sha256(f"artifact-{strategy}".encode()).hexdigest(),
        "regular_purchase_sha256": hashlib.sha256(f"purchase-{strategy}".encode()).hexdigest(),
        "reserve_amount": float(index * 10),
        "exact_training_objective": 1000.0 + index,
        "training_joint_scenario_set_sha256": "b" * 64,
    }


def _science(case: pilot.M21PilotCase) -> dict:
    plan_ids = (*pilot.CANDIDATE_IDS, "zero_autonomous_reserve", "fixed_autonomous_reserve_0_10", "fixed_autonomous_reserve_0_30", "fixed_autonomous_reserve_0_50")
    plans = {name: _plan_identity(name, index) for index, name in enumerate(plan_ids)}
    validation_identity = _scenario_identity("c")
    validation = {
        name: {
            "candidate_id": name,
            "reserve": plans[name]["reserve_amount"],
            "regular_purchase_sha256": plans[name]["regular_purchase_sha256"],
            "exact_training_objective": plans[name]["exact_training_objective"],
            "source_plan_identity": {
                field: plans[name][field] for field in pilot.PLAN_IDENTITY_FIELDS
            },
            "metrics": {
                "plan_oos_status": "complete_feasible", "optimal_scenario_count": 2000,
                "infeasible_scenario_count": 0, "solver_failure_count": 0,
                "mean_total_cost": 100.0 + index,
                "total_cost_cvar95": 110.0 + index, "service_level": 0.9,
            },
            **validation_identity,
        }
        for index, name in enumerate(pilot.CANDIDATE_IDS)
    }
    selection = pilot.select_validation_candidate({
        name: {
            "total_cost_cvar95": row["metrics"]["total_cost_cvar95"],
            "mean_total_cost": row["metrics"]["mean_total_cost"], "reserve": row["reserve"],
        }
        for name, row in validation.items()
    })
    test = {}
    test_identity = _scenario_identity("d") if case.includes_test_probe else None
    if case.includes_test_probe:
        strategy_sources = {
            "M2_minimum_endpoint": "minimum_endpoint",
            "M2_1_validation_selected_endpoint": selection["selected_candidate_id"],
            "zero_autonomous_reserve": "zero_autonomous_reserve",
            "fixed_autonomous_reserve_0_10": "fixed_autonomous_reserve_0_10",
            "fixed_autonomous_reserve_0_30": "fixed_autonomous_reserve_0_30",
            "fixed_autonomous_reserve_0_50": "fixed_autonomous_reserve_0_50",
        }
        for strategy, source in strategy_sources.items():
            plan = plans[source]
            test[strategy] = {
                "strategy_id": strategy, "source_candidate_id": source,
                "reserve": plan["reserve_amount"],
                "regular_purchase_sha256": plan["regular_purchase_sha256"],
                "exact_training_objective": plan["exact_training_objective"],
                "source_plan_identity": {
                    field: plan[field] for field in pilot.PLAN_IDENTITY_FIELDS
                },
                "metrics": {
                    "plan_oos_status": "complete_feasible", "optimal_scenario_count": 2000,
                    "infeasible_scenario_count": 0, "solver_failure_count": 0,
                    "mean_total_cost": 100.0, "total_cost_cvar95": 110.0,
                    "service_level": 0.9,
                },
                **test_identity,
            }
    return {
        "tier_id": "M2F2", "beta": 1.1, "profile_id": "T03",
        "training_seed": case.training_seed, "validation_seed": case.validation_seed,
        "test_seed": case.test_seed, "includes_test_probe": case.includes_test_probe,
        "budget": 2571.372016574617, "training_scenario_count": 100,
        "validation_scenario_count": 2000,
        "test_scenario_count": 2000 if case.includes_test_probe else 0,
        "training_scenario_identity": _scenario_identity("b"),
        "R_min_feas": 0.0, "R_min_opt": 10.0, "R_max_opt": 30.0,
        "complete_extensive_objective": 1000.0, "objective_tolerance": 0.1,
        "endpoint_failure_counts": {
            "minimum": {"infeasible": 0, "solver_failure": 0},
            "maximum": {"infeasible": 0, "solver_failure": 0},
        },
        "candidate_training": {}, "validation_results": validation,
        "validation_selection": selection, "validation_scenario_identity": validation_identity,
        "test_results": test, "test_scenario_identity": test_identity,
        "minimum_endpoint_control_candidate_id": "minimum_endpoint",
        "minimum_endpoint_generated_once": True,
        "first_stage_plan_artifacts": plans,
        "minimum_endpoint_M2_control_identity": {
            field: plans["minimum_endpoint"][field] for field in pilot.PLAN_IDENTITY_FIELDS
        },
        "solver": "gurobi_direct", "gurobi_optimizer_version": "13.0.2",
        "gurobipy_version": "13.0.2", "threads": 1,
    }


def test_frozen_pilot_is_exactly_three_indivisible_triplets() -> None:
    config, design = _configs()
    cases = pilot.build_pilot_cases(config, design)
    assert len(cases) == 3
    assert [case.triplet_position for case in cases] == [1, 2, 3]
    assert [(case.training_seed, case.validation_seed, case.test_seed) for case in cases] == [
        (2026090401, 2026090501, 2026090701),
        (2026090402, 2026090502, 2026090702),
        (2026090403, 2026090503, 2026090703),
    ]
    assert [case.includes_test_probe for case in cases] == [True, False, False]
    assert config["pilot_matrix"]["validation_exact_recourse_evaluation_count"] == 18000
    assert config["pilot_matrix"]["test_probe_exact_recourse_evaluation_count"] == 12000
    runner = yaml.safe_load(RUNNER.read_text(encoding="utf-8"))
    assert runner["solver"] == {
        "interface": "gurobi_direct", "optimizer_version": "13.0.2",
        "gurobipy_version": "13.0.2", "fallback_allowed": False,
    }
    assert runner["limits"]["threads"] == 1


def test_current_revision_cannot_execute_or_reach_fingerprints(monkeypatch) -> None:
    monkeypatch.setattr(pilot, "pilot_fingerprints", lambda *args, **kwargs: pytest.fail("fingerprints reached"))
    with pytest.raises(PermissionError, match="authorization is false"):
        pilot.validate_preflight(
            root=ROOT, pilot_path=CONFIG, runner_path=RUNNER,
            approval_path=APPROVAL, authorize=True,
        )


@pytest.mark.parametrize("target", ["parent", "base", "seed", "count", "identity", "gate", "formal"])
def test_pilot_config_tampering_is_rejected(target, tmp_path) -> None:
    payload = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    if target == "parent":
        payload["frozen_design"]["pr62_merge_tree"] = "0" * 40
    elif target == "base":
        payload["scientific_base"]["budget"] = 1.0
    elif target == "seed":
        payload["pilot_matrix"]["training_seeds"][0] += 1
    elif target == "count":
        payload["pilot_matrix"]["validation_exact_recourse_evaluation_count"] = 17999
    elif target == "identity":
        payload["identity_gates"]["validation_scenario_generated_once_per_triplet"] = False
    elif target == "gate":
        payload["compute_gate"]["projected_formal_wall_hours_maximum"] = 73.0
    else:
        payload["execution_boundaries"]["formal_test_authorized"] = True
    path = tmp_path / f"{target}.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError):
        pilot.load_pilot_config(path)


def test_future_frozen_revision_still_requires_explicit_cli_authorization(monkeypatch) -> None:
    config = pilot.load_pilot_config(CONFIG)
    monkeypatch.setattr(pilot, "load_pilot_config", lambda path: config)
    monkeypatch.setattr(pilot, "pilot_fingerprints", lambda *args, **kwargs: pytest.fail("fingerprints reached"))
    with pytest.raises(PermissionError, match="authorize-pilot"):
        pilot.validate_preflight(
            root=ROOT, pilot_path=CONFIG, runner_path=RUNNER,
            approval_path=APPROVAL, authorize=False,
        )


@pytest.mark.parametrize("phase,identity", [("validation", "validation_results"), ("test", "test_results")])
@pytest.mark.parametrize("field", pilot.SCENARIO_IDENTITY_FIELDS)
def test_projection_rejects_any_shared_scenario_identity_tamper(phase, identity, field) -> None:
    config, design = _configs(); case = pilot.build_pilot_cases(config, design)[0]
    science = _science(case)
    target = "interval_midpoint" if phase == "validation" else "fixed_autonomous_reserve_0_50"
    science[identity][target][field] = "e" * 64
    with pytest.raises(Exception, match="common_random_number_mismatch"):
        pilot._derive_triplet(science, case.as_dict())


@pytest.mark.parametrize("field", pilot.PLAN_IDENTITY_FIELDS)
def test_minimum_endpoint_control_identity_tamper_is_rejected(field) -> None:
    config, design = _configs(); case = pilot.build_pilot_cases(config, design)[0]
    science = _science(case)
    science["minimum_endpoint_M2_control_identity"][field] = (
        999.0 if field in {"reserve_amount", "exact_training_objective"} else "e" * 64
    )
    # The projection must bind the saved control record, not merely compare the plan to itself.
    with pytest.raises(ValueError, match="control identity"):
        pilot._derive_triplet(science, case.as_dict())


def test_validation_selection_is_independently_recomputed_and_test_is_not_used() -> None:
    config, design = _configs(); case = pilot.build_pilot_cases(config, design)[0]
    science = _science(case)
    assert pilot._derive_triplet(science, case.as_dict())["selected_candidate_id"] == "minimum_endpoint"
    science["validation_selection"]["selected_candidate_id"] = "maximum_endpoint"
    with pytest.raises(ValueError, match="independently reproduced"):
        pilot._derive_triplet(science, case.as_dict())


def test_projection_independently_closes_three_triplets_and_never_authorizes_formal(
    monkeypatch, tmp_path,
) -> None:
    config, design = _configs(); fingerprints = _fingerprints()
    cases = pilot.build_pilot_cases(config, design)
    results = {
        case.case_id: {
            "run_id": f"pilot_{case.case_id}", "case_id": case.case_id,
            "case": case.as_dict(), "status": "optimal", "wall_seconds": 30.0,
            "science": _science(case),
        }
        for case in cases
    }
    rows = [
        {
            "run_id": result["run_id"], "case_id": case_id, "status": "optimal",
            "parent_run_id": "", **fingerprints,
        }
        for case_id, result in results.items()
    ]
    monkeypatch.setattr(pilot, "_read_registry", lambda path: rows)
    monkeypatch.setattr(pilot, "_validate_artifact", lambda output, row: results[row["case_id"]])
    monkeypatch.setattr(pilot, "_validate_plan_artifact", lambda **kwargs: {})
    projection = pilot.update_projection(
        output_root=tmp_path, pilot=config, design=design, fingerprints=fingerprints,
    )
    assert projection["status"] == "complete"
    assert projection["verified_primary_run_count"] == 3
    assert projection["validation_candidate_plan_count"] == 9
    assert projection["validation_exact_recourse_evaluation_count"] == 18000
    assert projection["test_probe_plan_count"] == 6
    assert projection["test_probe_exact_recourse_evaluation_count"] == 12000
    assert projection["pilot_compute_gate_passed"] is True
    assert projection["formal_extension_authorized"] is False


def test_selected_minimum_reuses_control_and_has_zero_probe_difference() -> None:
    config, design = _configs(); case = pilot.build_pilot_cases(config, design)[0]
    science = _science(case)
    control = science["test_results"]["M2_minimum_endpoint"]
    treatment = science["test_results"]["M2_1_validation_selected_endpoint"]
    assert control["regular_purchase_sha256"] == treatment["regular_purchase_sha256"]
    treatment["metrics"]["total_cost_cvar95"] += 1.0
    with pytest.raises(Exception, match="differs"):
        pilot._derive_triplet(science, case.as_dict())


def test_primary_subset_and_unbound_diagnostic_are_forbidden(monkeypatch) -> None:
    config, design = _configs()
    monkeypatch.setattr(pilot, "validate_preflight", lambda **kwargs: {
        "pilot": config, "design": design,
        "runner": yaml.safe_load(RUNNER.read_text(encoding="utf-8")),
        "fingerprints": _fingerprints(), "locked_environment": {}, "source": {},
    })
    case_id = pilot.build_pilot_cases(config, design)[0].case_id
    with pytest.raises(ValueError, match="complete frozen"):
        pilot.run_pilot(
            root=ROOT, pilot_path=CONFIG, runner_path=RUNNER, approval_path=APPROVAL,
            authorize=True, run_id_prefix="safe", case_ids=[case_id],
        )
    with pytest.raises(ValueError, match="one case_id"):
        pilot.run_pilot(
            root=ROOT, pilot_path=CONFIG, runner_path=RUNNER, approval_path=APPROVAL,
            authorize=True, run_id_prefix="safe", parent_run_id="parent",
        )


@pytest.mark.parametrize("run_id", ["../escape", "a/b", "a\\b", "C:\\absolute"])
def test_run_id_cannot_escape_namespace(run_id, tmp_path) -> None:
    with pytest.raises(ValueError):
        pilot._run_directory(tmp_path, run_id)


def test_failure_is_finalized_and_stops_batch(monkeypatch, tmp_path) -> None:
    config, design = _configs(); case = pilot.build_pilot_cases(config, design)[0]
    runner_config = yaml.safe_load(RUNNER.read_text(encoding="utf-8"))
    monkeypatch.setattr(pilot, "load_phase6_matrix", lambda path: {})
    monkeypatch.setattr(pilot, "capture_runtime_context", lambda **kwargs: {})
    monkeypatch.setattr(pilot, "_write_registry", lambda *args, **kwargs: None)
    monkeypatch.setattr(pilot, "update_projection", lambda **kwargs: {"pilot_compute_gate_passed": False})

    def fail(**kwargs):
        kwargs["progress"]("validation_minimum_endpoint", {})
        raise RuntimeError("synthetic failure")

    output = tmp_path / "out"
    result = pilot.run_case(
        root=tmp_path, output_root=output, matrix_path=tmp_path / "matrix.yaml",
        pilot=config, design=design, runner=runner_config,
        fingerprints=_fingerprints(), locked_environment={},
        source={"commit_sha": "a" * 40, "tree_sha": "b" * 40},
        case=case, run_id="immutable_failure", science_executor=fail,
    )
    assert result["status"] == "stage_failure"
    path = output / "pilot/runs/immutable_failure/status_summary.json"
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "stage_failure"
    with pytest.raises(ValueError, match="immutable"):
        pilot.run_case(
            root=tmp_path, output_root=output, matrix_path=tmp_path / "matrix.yaml",
            pilot=config, design=design, runner=runner_config,
            fingerprints=_fingerprints(), locked_environment={},
            source={"commit_sha": "a" * 40, "tree_sha": "b" * 40},
            case=case, run_id="immutable_failure", science_executor=fail,
        )


def test_registry_writes_are_lock_serialized(tmp_path) -> None:
    output = tmp_path / "out"
    rows = [
        {"run_id": f"run_{index}", "case_id": f"case_{index}", "status": "optimal"}
        for index in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda row: pilot._write_registry(output, row), rows))
    observed = pilot._read_registry(output / "pilot/pilot_run_registry.csv")
    assert {row["run_id"] for row in observed} == {"run_0", "run_1"}


def test_registry_finalization_failure_writes_bounded_terminal_diagnostic(
    monkeypatch, tmp_path,
) -> None:
    config, design = _configs(); case = pilot.build_pilot_cases(config, design)[0]
    runner_config = yaml.safe_load(RUNNER.read_text(encoding="utf-8"))
    monkeypatch.setattr(pilot, "load_phase6_matrix", lambda path: {})
    monkeypatch.setattr(pilot, "capture_runtime_context", lambda **kwargs: {})
    monkeypatch.setattr(pilot, "_write_registry", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("locked registry")))
    with pytest.raises(PermissionError, match="locked registry"):
        pilot.run_case(
            root=tmp_path, output_root=tmp_path / "out", matrix_path=tmp_path / "matrix.yaml",
            pilot=config, design=design, runner=runner_config,
            fingerprints=_fingerprints(), locked_environment={},
            source={"commit_sha": "a" * 40, "tree_sha": "b" * 40},
            case=case, run_id="finalization_failure", science_executor=lambda **kwargs: {},
        )
    diagnostic = tmp_path / "out/pilot/runs/finalization_failure/runner_exception.json"
    payload = json.loads(diagnostic.read_text(encoding="utf-8"))
    assert payload["status"] == "runner_exception"
    assert payload["stage"] == "registry_finalization"
    assert len(diagnostic.read_bytes()) < MAX_BYTES


def test_cli_requires_projection_gate_even_with_three_optimal_runs(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "run_pilot", lambda **kwargs: [
        {"status": "optimal", "projection": {"pilot_compute_gate_passed": False}}
        for _ in range(3)
    ])
    code = cli.main(["--run-id-prefix", "pilot"])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "incomplete"


def test_bounded_status_reader_never_uses_result_or_checkpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.phase6_m2_1_pilot_status.OUTPUT_ROOT", "outputs/test")
    run = tmp_path / "outputs/test/pilot/runs/r1"; run.mkdir(parents=True)
    (run / "status_summary.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
    (run / "result.json").write_text("x" * (MAX_BYTES * 10), encoding="utf-8")
    assert read_status(tmp_path, "r1") == {"status": "running"}


def test_revision_records_zero_science_execution() -> None:
    config = pilot.load_pilot_config(CONFIG)
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    assert config["execution_boundaries"] == {
        "runner_implemented": True, "pilot_authorized": False,
        "formal_training_authorized": False, "formal_validation_authorized": False,
        "selected_plan_freeze_authorized": False, "formal_test_authorized": False,
        "formal_extension_authorized": False, "scenario_generation_count": 0,
        "gurobi_call_count": 0, "pilot_run_count": 0, "formal_run_count": 0,
        "algorithm_performance_runs": 0, "M0_E3_runs": 0,
    }
    assert all(value == 0 for value in approval["execution_counts_in_this_revision"].values())
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert all(value == 0 for value in audit["execution_counts"].values())
    assert audit["frozen_pilot"]["primary_run_count"] == 3
    assert audit["frozen_pilot"]["validation_candidate_plan_count"] == 9
    assert audit["frozen_pilot"]["validation_exact_recourse_evaluation_count"] == 18000
    assert audit["frozen_pilot"]["test_probe_plan_count"] == 6
    assert audit["frozen_pilot"]["test_probe_exact_recourse_evaluation_count"] == 12000
    assert audit["safety"]["formal_extension_authorized"] is False
    assert audit["CI"] == "recorded_in_pr_body"
