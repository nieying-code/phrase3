from __future__ import annotations

import copy
from contextlib import nullcontext
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.phase6_m2_1_endpoint_selection import PLAN_IDENTITY_FIELDS, TEST_STRATEGIES
from src.phase6_m2_1_formal_test import (
    APPROVAL_PATH,
    FREEZE_PATH,
    OUTPUT_ROOT,
    RUNNER_PATH,
    _derive_science,
    _load_freeze,
    _test_scenario_uniqueness,
    _validate_reviewed_freeze_audit,
    build_cases,
    execute_formal_test_science,
    run_formal_test,
    update_projection,
    validate_preflight,
)


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_batch_is_exactly_ten_by_six_by_two_thousand() -> None:
    freeze = _load_freeze(ROOT / FREEZE_PATH)
    cases = build_cases(freeze)
    assert len(cases) == 10
    assert [case.triplet_position for case in cases] == list(range(1, 11))
    assert len({case.test_seed for case in cases}) == 10
    assert freeze["scientific_scope"]["strategy_ids"] == list(TEST_STRATEGIES)
    assert 10 * 6 * 2000 == 120000


def test_current_revision_cannot_authorize_or_generate_scenarios(monkeypatch) -> None:
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("scenario generation must not be reached")

    monkeypatch.setattr("src.phase6_m2_1_pilot._generate_data", forbidden)
    with pytest.raises(PermissionError, match="approval"):
        validate_preflight(
            root=ROOT, freeze_path=ROOT / FREEZE_PATH,
            runner_path=ROOT / RUNNER_PATH, approval_path=ROOT / APPROVAL_PATH,
            authorize=True,
        )
    assert called is False


def test_explicit_cli_authorization_is_required() -> None:
    with pytest.raises(PermissionError, match="authorize-formal-test"):
        validate_preflight(
            root=ROOT, freeze_path=ROOT / FREEZE_PATH,
            runner_path=ROOT / RUNNER_PATH, approval_path=ROOT / APPROVAL_PATH,
            authorize=False,
        )


def test_reviewed_pr70_freeze_audit_uses_real_authorization_schema() -> None:
    audit = json.loads(
        (ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_selected_plan_freeze_v1_0_audit.json")
        .read_text(encoding="utf-8")
    )
    binding = {
        "sha256": "59842e3eb1437ff5a16fa8980e79400dab6504ded032db6d30ef5e5f60302f90"
    }
    _validate_reviewed_freeze_audit(audit, binding)

    for field, value in (
        ("selected_plan_freeze_authorized", False),
        ("formal_test_runner_implemented", True),
        ("formal_test_authorized", True),
        ("formal_extension_authorized", True),
    ):
        tampered = copy.deepcopy(audit)
        tampered["authorization"][field] = value
        with pytest.raises(RuntimeError, match="PR #70 freeze audit boundary mismatch"):
            _validate_reviewed_freeze_audit(tampered, binding)

    wrong_schema = copy.deepcopy(audit)
    wrong_schema["execution_boundaries"] = wrong_schema.pop("authorization")
    with pytest.raises(RuntimeError, match="PR #70 freeze audit boundary mismatch"):
        _validate_reviewed_freeze_audit(wrong_schema, binding)


def test_pr72_authorization_is_revoked_by_runner_fix_before_source_loading() -> None:
    with pytest.raises(RuntimeError, match="orchestrator mismatch"):
        validate_preflight(
            root=ROOT,
            freeze_path=ROOT / FREEZE_PATH,
            runner_path=ROOT / RUNNER_PATH,
            approval_path=ROOT / "configs/phase6_m2_1_formal_test_authorization_v1_0.yaml",
            authorize=True,
        )


def _science_fixture():
    freeze = _load_freeze(ROOT / FREEZE_PATH); case = build_cases(freeze)[0]
    identity = {field: "a" * 64 for field in (
        "scenario_set_sha256", "scenario_order_sha256", "latent_draw_sha256",
        "demand_sha256", "emergency_price_sha256", "emergency_supply_sha256",
        "fulfillment_sha256",
    )}
    source_plans = {}
    plan_ids = {
        "M2_minimum_endpoint": "minimum_endpoint",
        "M2_1_validation_selected_endpoint": case.selected_candidate_id,
        "zero_autonomous_reserve": "zero_autonomous_reserve",
        "fixed_autonomous_reserve_0_10": "fixed_autonomous_reserve_0_10",
        "fixed_autonomous_reserve_0_30": "fixed_autonomous_reserve_0_30",
        "fixed_autonomous_reserve_0_50": "fixed_autonomous_reserve_0_50",
    }
    for index, source_id in enumerate(set(plan_ids.values())):
        source_plans[source_id] = {
            "finalized_plan_artifact_sha256": f"{index + 1:064x}",
            "regular_purchase_sha256": f"{index + 11:064x}",
            "reserve_amount": float(index), "exact_training_objective": 100.0 + index,
            "training_joint_scenario_set_sha256": "b" * 64,
        }
    results = {}
    for strategy_id, source_id in plan_ids.items():
        results[strategy_id] = {
            "strategy_id": strategy_id, "source_candidate_id": source_id,
            "source_run_id": case.source_run_id, "source_case_id": case.case_id,
            "plan_identity": {field: source_plans[source_id][field] for field in PLAN_IDENTITY_FIELDS},
            "test_scenario_identity": copy.deepcopy(identity), "test_scenario_count": 2000,
            "wall_seconds": 1.0,
            "metrics": {"plan_oos_status":"complete_feasible", "optimal_scenario_count":2000,
                        "infeasible_scenario_count":0, "solver_failure_count":0,
                        "mean_total_cost":10.0, "total_cost_cvar95":20.0, "service_level":0.9},
        }
    science = {"tier_id":"M2F2", "beta":1.1, "profile_id":"T03",
               "training_seed":case.training_seed, "validation_seed":case.validation_seed,
               "test_seed":case.test_seed, "selected_candidate_id":case.selected_candidate_id,
               "source_run_id":case.source_run_id, "test_scenario_count":2000,
               "test_scenario_identity":copy.deepcopy(identity),
               "solver":"gurobi_direct", "gurobi_optimizer_version":"13.0.2",
               "gurobipy_version":"13.0.2", "threads":1, "strategy_results":results}
    source = {"science":{"first_stage_plan_artifacts":source_plans}}
    return science, case, source


def test_projection_derivation_recomputes_plan_crn_and_evaluation_bindings() -> None:
    science, case, source = _science_fixture()
    assert _derive_science(science, case, source) == 12000


def _primary_scenario_fixture() -> dict[str, dict]:
    freeze = _load_freeze(ROOT / FREEZE_PATH)
    primary = {}
    for index, case in enumerate(build_cases(freeze), start=1):
        identity = {
            "scenario_set_sha256": f"{index:064x}",
            "scenario_order_sha256": f"{index + 20:064x}",
            "latent_draw_sha256": f"{index + 40:064x}",
            "demand_sha256": f"{index + 60:064x}",
            "emergency_price_sha256": f"{index + 80:064x}",
            "emergency_supply_sha256": f"{index + 100:064x}",
            "fulfillment_sha256": f"{index + 120:064x}",
        }
        primary[case.case_id] = {
            "status": "optimal", "science": {"test_scenario_identity": identity},
        }
    return primary


def test_projection_recomputes_ten_unique_test_scenario_identities() -> None:
    result = _test_scenario_uniqueness(_primary_scenario_fixture())
    assert result["verified_unique_test_scenario_set_count"] == 10
    assert result["verified_unique_test_scenario_identity_count"] == 10
    assert len(result["test_scenario_identity_mapping_sha256"]) == 64
    assert result["duplicate_test_scenario_identity_case_ids"] == []


def test_projection_rejects_two_runs_sharing_one_test_scenario_identity() -> None:
    primary = _primary_scenario_fixture()
    first, second = list(primary)[:2]
    primary[second]["science"]["test_scenario_identity"] = copy.deepcopy(
        primary[first]["science"]["test_scenario_identity"]
    )
    result = _test_scenario_uniqueness(primary)
    assert result["verified_unique_test_scenario_set_count"] == 9
    assert result["verified_unique_test_scenario_identity_count"] == 9
    assert result["duplicate_test_scenario_identity_case_ids"] == [first, second]


def test_projection_gate_rejects_duplicate_test_units(monkeypatch, tmp_path) -> None:
    freeze = _load_freeze(ROOT / FREEZE_PATH); cases = build_cases(freeze)
    primary = _primary_scenario_fixture(); first, second = list(primary)[:2]
    primary[second]["science"]["test_scenario_identity"] = copy.deepcopy(
        primary[first]["science"]["test_scenario_identity"]
    )
    rows = [
        {"run_id": f"run_{index}", "case_id": case.case_id,
         "parent_run_id": "", "fingerprint": "locked",
         "formal_test_orchestrator_sha256": "o" * 64}
        for index, case in enumerate(cases, start=1)
    ]
    results = {
        row["run_id"]: {
            "run_id": row["run_id"], "case_id": row["case_id"], "status": "optimal",
            "science": {**primary[row["case_id"]]["science"],
                        "strategy_results": {strategy: {} for strategy in TEST_STRATEGIES}},
        }
        for row in rows
    }
    monkeypatch.setattr("src.phase6_m2_1_formal_test._read_registry", lambda path: rows)
    monkeypatch.setattr("src.phase6_m2_1_formal_test._validate_artifact", lambda output, row, fingerprints, orchestrator: results[row["run_id"]])
    monkeypatch.setattr("src.phase6_m2_1_formal_test._derive_science", lambda science, case, source: 12000)
    monkeypatch.setattr("src.phase6_m2_1_formal_test._finalization_failures", lambda base: [])
    payload = update_projection(
        output_root=tmp_path, freeze=freeze, fingerprints={"fingerprint":"locked"},
        orchestrator="o" * 64, sources={case.case_id:{} for case in cases},
    )
    assert payload["completed_primary_run_count"] == 10
    assert payload["completed_exact_recourse_evaluation_count"] == 120000
    assert payload["verified_unique_test_scenario_set_count"] == 9
    assert payload["duplicate_test_scenario_identity_case_ids"] == [first, second]
    assert payload["formal_test_gate_passed"] is False


@pytest.mark.parametrize("mutation", ["plan", "scenario", "count", "solver", "nan"])
def test_projection_rejects_tampered_scientific_evidence(mutation: str) -> None:
    science, case, source = _science_fixture(); science = copy.deepcopy(science)
    first = science["strategy_results"][TEST_STRATEGIES[0]]
    if mutation == "plan": first["plan_identity"]["reserve_amount"] += 1
    elif mutation == "scenario": first["test_scenario_identity"]["demand_sha256"] = "c" * 64
    elif mutation == "count": first["metrics"]["optimal_scenario_count"] = 1999
    elif mutation == "solver": science["threads"] = 2
    else: first["metrics"]["total_cost_cvar95"] = float("nan")
    with pytest.raises(ValueError): _derive_science(science, case, source)


def test_primary_batch_cannot_be_subset_and_prior_authorization_is_rejected(monkeypatch, tmp_path) -> None:
    freeze = _load_freeze(ROOT / FREEZE_PATH); cases = build_cases(freeze)
    fake = {"freeze":freeze,"runner":{"limits":{}},"fingerprints":{},"orchestrator":"a"*64,
            "cases":cases,"sources":{},"source":{},"locked_environment":{}}
    monkeypatch.setattr("src.phase6_m2_1_formal_test.validate_preflight", lambda **kwargs: fake)
    with pytest.raises(ValueError, match="complete frozen"):
        run_formal_test(root=tmp_path,freeze_path=tmp_path/"f",runner_path=tmp_path/"r",
                        approval_path=tmp_path/"a",authorize=True,run_id_prefix="safe",
                        case_ids=[cases[0].case_id])


def test_runner_and_approval_freeze_all_safety_boundaries() -> None:
    runner = yaml.safe_load((ROOT / RUNNER_PATH).read_text(encoding="utf-8"))
    approval = yaml.safe_load((ROOT / APPROVAL_PATH).read_text(encoding="utf-8"))
    assert runner["limits"] == {"solver_call_seconds":120,"test_plan_wall_seconds":7200,"threads":1}
    assert runner["execution"]["six_strategies_are_evaluated_independently"] is True
    assert runner["execution"]["formal_test_recourse_evaluation_count"] == 120000
    assert approval["selected_plan_freeze_authorized"] is True
    assert approval["formal_test_runner_implemented"] is True
    assert approval["formal_test_authorized"] is False
    assert approval["formal_extension_authorized"] is False
    assert approval["algorithm_performance_authorized"] is False
    assert all(value == 0 for value in approval["execution_counts_in_this_revision"].values())


def test_six_logical_strategies_are_independently_evaluated_on_one_test_set(monkeypatch) -> None:
    freeze = _load_freeze(ROOT / FREEZE_PATH)
    case = next(case for case in build_cases(freeze) if case.selected_candidate_id == "minimum_endpoint")
    identity = {field: "a" * 64 for field in (
        "scenario_set_sha256", "scenario_order_sha256", "latent_draw_sha256",
        "demand_sha256", "emergency_price_sha256", "emergency_supply_sha256",
        "fulfillment_sha256",
    )}
    generated = SimpleNamespace(data=SimpleNamespace())
    calls = []
    monkeypatch.setattr("src.phase6_m2_1_formal_test._generate_data", lambda **kwargs: (generated, 2571.372016574617))
    monkeypatch.setattr("src.phase6_m2_1_formal_test._scenario_identity", lambda value: identity)
    monkeypatch.setattr("src.phase6_m2_1_formal_test.m2_model_context", nullcontext)
    monkeypatch.setattr("src.phase6_m2_1_formal_test._load_plan", lambda root, source, strategy_id: {
        "strategy_id": strategy_id, "regular_purchase": {}, "reserve_amount": 1.0,
        "finalized_plan_artifact_sha256": "1" * 64,
        "regular_purchase_sha256": "2" * 64, "exact_training_objective": 3.0,
        "training_joint_scenario_set_sha256": "4" * 64,
    })
    def evaluate(*args, **kwargs):
        calls.append(args[1]); return object()
    monkeypatch.setattr("src.phase6_m2_1_formal_test._evaluate_plan_with_wall_limit", evaluate)
    monkeypatch.setattr("src.phase6_m2_1_formal_test.aggregate_oos_evaluation", lambda *args, **kwargs: {
        "plan_oos_status":"complete_feasible", "optimal_scenario_count":2000,
        "infeasible_scenario_count":0, "solver_failure_count":0,
        "mean_total_cost":10.0, "total_cost_cvar95":20.0, "service_level":0.9,
    })
    monkeypatch.setattr("src.phase6_m2_1_formal_test._cross_item_from_evaluation", lambda *args: {"status":"defined"})
    science = execute_formal_test_science(
        project_root=ROOT, matrix={}, matrix_path=ROOT/"matrix.yaml", case=case,
        source_result={"run_id":case.source_run_id,"case_id":case.case_id,"science":{}},
        progress=lambda *args: None,
        runner_limits={"solver_call_seconds":120,"test_plan_wall_seconds":7200,"threads":1},
    )
    assert len(calls) == 6
    assert set(science["strategy_results"]) == set(TEST_STRATEGIES)
    assert len({json.dumps(row["test_scenario_identity"], sort_keys=True) for row in science["strategy_results"].values()}) == 1


def test_timeout_stops_before_second_strategy(monkeypatch) -> None:
    freeze = _load_freeze(ROOT / FREEZE_PATH); case = build_cases(freeze)[0]
    monkeypatch.setattr("src.phase6_m2_1_formal_test._generate_data", lambda **kwargs: (SimpleNamespace(data=SimpleNamespace()), 1.0))
    monkeypatch.setattr("src.phase6_m2_1_formal_test._scenario_identity", lambda value: {str(i):"a"*64 for i in range(7)})
    monkeypatch.setattr("src.phase6_m2_1_formal_test.m2_model_context", nullcontext)
    monkeypatch.setattr("src.phase6_m2_1_formal_test._load_plan", lambda *args, **kwargs: {"regular_purchase":{},"reserve_amount":0.0})
    calls = 0
    def timeout(*args, **kwargs):
        nonlocal calls; calls += 1; raise TimeoutError("time_limit")
    monkeypatch.setattr("src.phase6_m2_1_formal_test._evaluate_plan_with_wall_limit", timeout)
    with pytest.raises(TimeoutError):
        execute_formal_test_science(project_root=ROOT,matrix={},matrix_path=ROOT/"m",case=case,
            source_result={"run_id":case.source_run_id,"case_id":case.case_id,"science":{}},
            progress=lambda *args:None,runner_limits={"solver_call_seconds":120,"test_plan_wall_seconds":7200,"threads":1})
    assert calls == 1


def test_formal_test_output_namespace_does_not_exist() -> None:
    assert not (ROOT / OUTPUT_ROOT).exists()
