from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from contextlib import nullcontext

import pytest
import yaml

from src import phase6_m2_formal_oos as oos
from src import run_phase6_m2_formal_oos as oos_cli
from src.evaluation import EvaluationResult
from src.phase6_m2_formal_extension import formal_extension_fingerprints, load_formal_extension_config
from src.phase6_m2_formal_oos_status import _bounded


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/phase6_m2_formal_extension.yaml"
PILOT_RUNNER = ROOT / "configs/phase6_m2_formal_extension_runner.yaml"
RUNNER = ROOT / "configs/phase6_m2_formal_oos_runner.yaml"
APPROVAL = ROOT / "configs/phase6_m2_formal_oos_approval.yaml"
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": "02d50abd609acd9d93eca6b13f6195e6eee14330e3db5c5ca75e83d2e7b56612",
    "e3_component_sha256": "87f643fd3bf90f825251641c1bdeeb25f4aebb1ea23d052913b27e0b5fdf2924",
    "family_component_sha256": "b1f9278ee8a0085e80c418f33d04c92b943c215eaf9ca2cdb6144e8dcebdb68b",
    "runner_config_sha256": "c8d9efb59649b2a3e16839cdece7c38bc5a385358c354b72310c32134f49ad8e",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}


def _preflight_payload(root: Path) -> dict:
    return {
        "config": load_formal_extension_config(CONFIG),
        "runner": yaml.safe_load(RUNNER.read_text(encoding="utf-8")),
        "fingerprints": EXPECTED_FINGERPRINTS,
        "formal_OOS_orchestrator_sha256": "a" * 64,
        "source_mechanism_results": {
            seed: {"run_id": f"source_{seed}"}
            for seed in range(2026081401, 2026081411)
        },
        "locked_environment": {},
        "source": {"commit_sha": "b" * 40, "tree_sha": "c" * 40},
    }


def test_formal_oos_matrix_is_exactly_ten_paired_cases():
    config = load_formal_extension_config(CONFIG)
    cases = oos.build_formal_oos_cases(config)
    assert len(cases) == 10
    assert [(case.seed, case.test_seed) for case in cases] == list(zip(
        range(2026081401, 2026081411), range(2026081501, 2026081511), strict=True,
    ))
    assert all(
        case.run_kind == "formal_OOS"
        and case.tier_id == "M2F2"
        and case.beta == 1.1
        and case.profile_id == "T03"
        for case in cases
    )


def test_oos_layer_preserves_science_fingerprints_and_starts_with_zero_runs():
    actual = formal_extension_fingerprints(ROOT, CONFIG, PILOT_RUNNER)
    for field in (
        "scientific_config_sha256", "e3_component_sha256",
        "family_component_sha256", "runner_config_sha256",
    ):
        assert actual[field] == EXPECTED_FINGERPRINTS[field]
    assert len(actual["environment_sha256"]) == 64
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    runner = yaml.safe_load(RUNNER.read_text(encoding="utf-8"))
    assert approval["approved_fingerprints"] == EXPECTED_FINGERPRINTS
    assert approval["formal_OOS_authorized"] is True
    assert approval["algorithm_performance_authorized"] is False
    assert approval["execution_counts_in_this_revision"] == {
        "formal_OOS_primary_runs": 0,
        "formal_OOS_plans": 0,
        "formal_OOS_recourse_evaluations": 0,
        "algorithm_performance_runs": 0,
        "M0_E3_runs": 0,
    }
    assert runner["output_root"] == oos.OOS_OUTPUT_ROOT
    assert runner["source_output_root"] == oos.SOURCE_OUTPUT_ROOT
    assert runner["execution"]["reviewed_mechanism_evidence_is_read_only"] is True
    assert runner["limits"] == {
        "solver_call_seconds": 120,
        "OOS_plan_wall_seconds": 7200,
        "threads": 1,
    }


def test_preflight_rejects_any_frozen_limit_change_before_evidence_access(
    monkeypatch, tmp_path,
):
    runner = yaml.safe_load(RUNNER.read_text(encoding="utf-8"))
    runner["limits"]["OOS_plan_wall_seconds"] = 7201
    changed = tmp_path / "runner.yaml"
    changed.write_text(yaml.safe_dump(runner), encoding="utf-8")
    touched = False

    def forbidden(*args, **kwargs):
        nonlocal touched
        touched = True
        raise AssertionError("fingerprints/evidence must not be read")

    monkeypatch.setattr(oos, "formal_extension_fingerprints", forbidden)
    with pytest.raises(RuntimeError, match="frozen execution limits mismatch"):
        oos.validate_formal_oos_preflight(
            root=ROOT, config_path=CONFIG, runner_path=changed,
            approval_path=APPROVAL, authorize=True,
        )
    assert touched is False


def test_plan_wall_limit_stops_before_next_scenario_or_strategy():
    ticks = iter((0.0, 0.0, 7199.0, 7200.01))
    calls = []
    data = SimpleNamespace(
        scenarios=("s1", "s2"), items=("item",), periods=1,
        regular_price={"item": (1.0,)},
    )

    def evaluator(data, purchase, reserve, **kwargs):
        calls.append(kwargs)
        return EvaluationResult(
            status="optimal", regular_cost=1.0, robust_objective=2.0,
            worst_scenario="s1", worst_recourse_cost=1.0,
            scenario_results={"s1": SimpleNamespace(status="optimal", objective=1.0)},
            infeasible_scenarios=(), failed_scenarios=(), runtime_seconds=1.0,
        )

    with pytest.raises(TimeoutError, match="OOS_plan_wall_seconds"):
        oos._evaluate_plan_with_wall_limit(
            data, {"item": (1.0,)}, 0.0,
            solver_call_seconds=120.0, plan_wall_seconds=7200.0,
            evaluator=evaluator, clock=lambda: next(ticks),
        )
    assert len(calls) == 1
    assert calls[0]["scenario_names"] == ("s1",)
    assert calls[0]["time_limit_seconds"] == 120.0


def test_cli_returns_nonzero_when_all_runs_are_optimal_but_gate_fails(monkeypatch, capsys):
    monkeypatch.setattr(oos_cli, "run_formal_oos", lambda **kwargs: [
        {"status": "optimal", "formal_OOS_progress": {"formal_OOS_gate_passed": False}}
        for _ in range(10)
    ])
    code = oos_cli.main([
        "--run-id-prefix", "formal_oos",
        "--authorize-formal-oos-execution",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["status"] == "incomplete"
    assert payload["formal_OOS_gate_passed"] is False


def test_preflight_rejects_missing_cli_authorization_before_evidence_access(monkeypatch):
    touched = False

    def forbidden(*args, **kwargs):
        nonlocal touched
        touched = True
        raise AssertionError("evidence must not be read")

    monkeypatch.setattr(oos, "formal_extension_fingerprints", forbidden)
    with pytest.raises(PermissionError, match="authorize-formal-oos-execution"):
        oos.validate_formal_oos_preflight(
            root=ROOT, config_path=CONFIG, runner_path=RUNNER,
            approval_path=APPROVAL, authorize=False,
        )
    assert touched is False


def test_local_registry_and_approval_cannot_replace_reviewed_audit_binding(monkeypatch, tmp_path):
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    audit_source = ROOT / approval["mechanism_evidence"]["audit_path"]
    audit_path = tmp_path / approval["mechanism_evidence"]["audit_path"]
    registry_path = tmp_path / approval["mechanism_evidence"]["registry_path"]
    progress_path = tmp_path / approval["mechanism_evidence"]["progress_path"]
    for path in (audit_path, registry_path, progress_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_bytes(audit_source.read_bytes())
    registry_path.write_text("run_id,status\nreplacement,optimal\n", encoding="utf-8")
    progress_path.write_text(json.dumps({
        "fingerprints": EXPECTED_FINGERPRINTS,
        "formal_mechanism_gate_passed": True,
        "formal_OOS_authorized": False,
    }), encoding="utf-8")
    approval["mechanism_evidence"]["registry_sha256"] = hashlib.sha256(
        registry_path.read_bytes()
    ).hexdigest()
    approval["mechanism_evidence"]["progress_sha256"] = hashlib.sha256(
        progress_path.read_bytes()
    ).hexdigest()
    with pytest.raises(RuntimeError, match="not bound to the PR #58 audit"):
        oos._validate_source_evidence(
            root=tmp_path, approval=approval, fingerprints=EXPECTED_FINGERPRINTS,
        )


def test_primary_execution_cannot_select_cases(monkeypatch, tmp_path):
    monkeypatch.setattr(oos, "validate_formal_oos_preflight", lambda **kwargs: _preflight_payload(tmp_path))
    with pytest.raises(ValueError, match="complete frozen ten-case batch"):
        oos.run_formal_oos(
            root=tmp_path, config_path=CONFIG, runner_path=RUNNER,
            approval_path=APPROVAL, authorize=True, run_id_prefix="formal_oos",
            case_ids=[oos.build_formal_oos_cases(load_formal_extension_config(CONFIG))[0].case_id],
        )


@pytest.mark.parametrize("terminal_status", ["stage_failure", "timeout"])
def test_primary_batch_is_serial_and_stops_on_first_failure(
    monkeypatch, tmp_path, terminal_status,
):
    monkeypatch.setattr(oos, "validate_formal_oos_preflight", lambda **kwargs: _preflight_payload(tmp_path))
    calls = []

    def fake_case(**kwargs):
        calls.append(kwargs["case"].case_id)
        return {"status": terminal_status, "formal_OOS_progress": {}}

    monkeypatch.setattr(oos, "run_formal_oos_case", fake_case)
    rows = oos.run_formal_oos(
        root=tmp_path, config_path=CONFIG, runner_path=RUNNER,
        approval_path=APPROVAL, authorize=True, run_id_prefix="formal_oos",
    )
    assert len(rows) == len(calls) == 1
    assert rows[0]["status"] == terminal_status


def test_plan_wall_timeout_is_finalized_as_immutable_terminal(monkeypatch, tmp_path):
    config = load_formal_extension_config(CONFIG)
    case = oos.build_formal_oos_cases(config)[0]
    monkeypatch.setattr(oos, "load_phase6_matrix", lambda path: {})
    monkeypatch.setattr(oos, "capture_runtime_context", lambda **kwargs: {})
    monkeypatch.setattr(oos, "_write_registry", lambda *args, **kwargs: None)
    monkeypatch.setattr(oos, "update_formal_oos_progress", lambda **kwargs: {
        "formal_OOS_gate_passed": False,
    })

    def timed_out(**kwargs):
        kwargs["progress"]("OOS_evaluate_endogenous_reserve", {
            "strategy_id": "endogenous_reserve",
        })
        raise TimeoutError("OOS_plan_wall_seconds exceeded")

    result = oos.run_formal_oos_case(
        root=ROOT, output_root=tmp_path,
        matrix_path=ROOT / "configs/phase6_experiment_matrix.yaml",
        config=config, fingerprints=EXPECTED_FINGERPRINTS,
        orchestrator_sha256="d" * 64, locked_environment={},
        source={"commit_sha": "b" * 40, "tree_sha": "c" * 40},
        source_mechanism_results={case.seed: {"run_id": "source"}},
        case=case, run_id="oos_timeout", science_executor=timed_out,
    )
    assert result["status"] == "timeout"
    assert result["failure"]["stage"] == "OOS_evaluate_endogenous_reserve"
    assert result["formal_OOS_progress"]["formal_OOS_gate_passed"] is False
    finalized = json.loads((
        tmp_path / oos.OOS_SUBDIRECTORY / "runs/oos_timeout/result.json"
    ).read_text(encoding="utf-8"))
    assert finalized["status"] == "timeout"
    assert finalized["finalized"] is True


def test_existing_oos_namespace_blocks_primary_batch(monkeypatch, tmp_path):
    monkeypatch.setattr(oos, "validate_formal_oos_preflight", lambda **kwargs: _preflight_payload(tmp_path))
    base = tmp_path / oos.OOS_OUTPUT_ROOT / oos.OOS_SUBDIRECTORY
    base.mkdir(parents=True)
    (base / "existing.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="empty OOS namespace"):
        oos.run_formal_oos(
            root=tmp_path, config_path=CONFIG, runner_path=RUNNER,
            approval_path=APPROVAL, authorize=True, run_id_prefix="formal_oos",
        )


def test_science_executor_uses_all_five_finalized_source_plans_without_reoptimization(
    monkeypatch, tmp_path,
):
    case = oos.build_formal_oos_cases(load_formal_extension_config(CONFIG))[0]
    identities = {
        strategy: {
            "strategy_id": strategy,
            "finalized_plan_artifact_sha256": hashlib.sha256(strategy.encode()).hexdigest(),
            "regular_purchase_sha256": hashlib.sha256(f"purchase-{strategy}".encode()).hexdigest(),
            "reserve_amount": float(index),
            "exact_training_objective": 100.0 + index,
            "training_joint_scenario_set_sha256": "1" * 64,
        }
        for index, strategy in enumerate(oos.REQUIRED_STRATEGIES)
    }
    source = {
        "run_id": "reviewed_source",
        "status": "optimal",
        "case": {"run_kind": "mechanism", "seed": case.seed, "beta": 1.1, "profile_id": "T03"},
        "science": {
            "joint_scenario_set_sha256": "1" * 64,
            "first_stage_plan_artifacts": identities,
        },
    }
    validated = []

    def validate_plan(**kwargs):
        identity = kwargs["identity"]
        validated.append(identity["strategy_id"])
        return {
            **identity,
            "regular_purchase": {"relief_food_1": [1.0], "relief_food_2": [2.0]},
        }

    fake_data = SimpleNamespace(
        storage_capacity=(1.0,) * 6,
        scenarios=("s0001",), items=("relief_food_1", "relief_food_2"), periods=1,
        regular_price={"relief_food_1": (1.0,), "relief_food_2": (1.0,)},
    )
    generated = SimpleNamespace(
        data=fake_data,
        joint_scenario_set_sha256="2" * 64,
        scenario_identities=[{}] * 2000,
    )
    calls = []

    def evaluate(data, purchase, reserve, **kwargs):
        calls.append((data, purchase, reserve, kwargs))
        return EvaluationResult(
            status="optimal", regular_cost=3.0, robust_objective=4.0,
            worst_scenario="s0001", worst_recourse_cost=1.0,
            scenario_results={
                "s0001": SimpleNamespace(status="optimal", objective=1.0),
            },
            infeasible_scenarios=(), failed_scenarios=(), runtime_seconds=0.01,
        )

    monkeypatch.setattr(oos, "_validate_formal_plan_artifact", validate_plan)
    monkeypatch.setattr(oos, "_confirmation_config", lambda root: {})
    monkeypatch.setattr(
        oos, "_validate_formal_baseline_before_generation",
        lambda *args, **kwargs: ({}, 10.0, 11.0, (1.0,) * 6),
    )
    monkeypatch.setattr(oos, "generate_oos_data", lambda *args, **kwargs: generated)
    monkeypatch.setattr(oos, "reconstruct_frozen_demand_latent", lambda *args: {})
    monkeypatch.setattr(oos, "_science_config_for_formal", lambda *args: {})
    monkeypatch.setattr(oos, "resolve_supply_disruption_profile", lambda *args: {})
    monkeypatch.setattr(oos, "apply_m2c2_supply_disruption", lambda *args, **kwargs: generated)
    monkeypatch.setattr(oos, "m2_model_context", nullcontext)
    monkeypatch.setattr(oos, "evaluate_first_stage", evaluate)
    monkeypatch.setattr(oos, "aggregate_oos_evaluation", lambda *args, **kwargs: {
        "plan_oos_status": "complete_feasible",
        "optimal_scenario_count": 2000,
        "infeasible_scenario_count": 0,
        "solver_failure_count": 0,
        "mean_total_cost": 1.0,
        "total_cost_p95": 1.0,
        "total_cost_cvar95": 1.0,
        "service_level": 1.0,
        "shortage_probability": 0.0,
        "mean_emergency_spend": 0.0,
    })
    monkeypatch.setattr(oos, "_cross_item_from_evaluation", lambda *args: {
        "scenario_item_emergency_spend_sha256": "3" * 64,
        "positive_total_emergency_spend_scenario_count": 0,
        "both_items_each_positive_in_at_least_one_scenario": False,
        "item1_emergency_spend_share_range": 0.0,
    })
    monkeypatch.setattr(oos, "_confirmation_component_hashes", lambda generated: {
        field: "4" * 64 for field in (
            "latent_draw_sha256", "demand_sha256", "fulfillment_sha256",
            "emergency_price_sha256", "emergency_supply_sha256", "scenario_order_sha256",
        )
    })
    derived = []
    monkeypatch.setattr(oos, "_derive_probe", lambda science, case_row, source_row: derived.append(
        (science, case_row, source_row)
    ))
    science = oos.execute_formal_oos_science(
        project_root=tmp_path, matrix={}, matrix_path=tmp_path / "matrix.yaml",
        config={"compute_gate": {"per_solver_call_seconds": 120}}, case=case,
        source_mechanism_result=source, progress=lambda *args: None,
    )
    assert validated == list(oos.REQUIRED_STRATEGIES)
    assert len(calls) == 5
    assert [call[2] for call in calls] == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert all(call[0] is fake_data for call in calls)
    assert all(call[3]["scenario_names"] == ("s0001",) for call in calls)
    assert all(call[3]["time_limit_seconds"] == 120.0 for call in calls)
    assert all(call[3]["solver_threads"] == 1 for call in calls)
    assert tuple(science["strategy_results"]) == oos.REQUIRED_STRATEGIES
    assert science["source_mechanism_run_id"] == "reviewed_source"
    assert derived and derived[0][2] is source


def test_registry_artifact_path_cannot_cross_run_or_namespace(tmp_path):
    row = {
        "run_id": "expected_run",
        "result_path": str((tmp_path / "other/result.json").resolve()),
        "manifest_path": str((tmp_path / "other/manifest.json").resolve()),
    }
    with pytest.raises(ValueError, match="leaves formal OOS namespace"):
        oos._controlled_artifact_paths(tmp_path, row)


def test_progress_recomputes_ten_runs_fifty_plans_and_one_hundred_thousand_scenarios(
    monkeypatch, tmp_path,
):
    config = load_formal_extension_config(CONFIG)
    cases = oos.build_formal_oos_cases(config)
    rows = []
    results = {}
    sources = {}
    for index, case in enumerate(cases):
        run_id = f"oos_{index}"
        rows.append({
            "run_id": run_id, "parent_run_id": "", "case_id": case.case_id,
            "status": "optimal", **EXPECTED_FINGERPRINTS,
            "formal_OOS_orchestrator_sha256": "d" * 64,
        })
        results[run_id] = {
            "run_id": run_id, "case_id": case.case_id, "status": "optimal",
            "case": case.as_dict(),
            "science": {"strategy_results": {
                strategy: {"metrics": {"optimal_scenario_count": 2000}}
                for strategy in oos.REQUIRED_STRATEGIES
            }},
        }
        sources[case.seed] = {"run_id": f"source_{case.seed}"}
    monkeypatch.setattr(oos, "_read_registry", lambda path: rows)
    monkeypatch.setattr(oos, "_validate_artifact", lambda output_root, row, **kwargs: results[row["run_id"]])
    monkeypatch.setattr(oos, "_derive_probe", lambda science, case, source: {})
    monkeypatch.setattr(oos, "_finalization_failure_ids", lambda base: [])
    progress = oos.update_formal_oos_progress(
        output_root=tmp_path, config=config, fingerprints=EXPECTED_FINGERPRINTS,
        orchestrator_sha256="d" * 64, source_mechanism_results=sources,
    )
    assert progress["status"] == "complete"
    assert progress["completed_primary_run_count"] == 10
    assert progress["completed_plan_count"] == 50
    assert progress["completed_exact_recourse_evaluation_count"] == 100000
    assert progress["formal_OOS_gate_passed"] is True
    assert progress["next_decision"] == "permit_OOS_results_review_only"
    assert progress["algorithm_performance_authorized"] is False


def test_failed_primary_permanently_blocks_oos_gate(monkeypatch, tmp_path):
    config = load_formal_extension_config(CONFIG)
    case = oos.build_formal_oos_cases(config)[0]
    rows = [
        {"run_id": "failed", "parent_run_id": "", "case_id": case.case_id,
         "status": "stage_failure", **EXPECTED_FINGERPRINTS,
         "formal_OOS_orchestrator_sha256": "d" * 64},
        {"run_id": "later", "parent_run_id": "", "case_id": case.case_id,
         "status": "optimal", **EXPECTED_FINGERPRINTS,
         "formal_OOS_orchestrator_sha256": "d" * 64},
    ]
    results = {
        "failed": {"run_id": "failed", "case_id": case.case_id, "status": "stage_failure", "case": case.as_dict(), "science": {}},
        "later": {"run_id": "later", "case_id": case.case_id, "status": "optimal", "case": case.as_dict(), "science": {}},
    }
    monkeypatch.setattr(oos, "_read_registry", lambda path: rows)
    monkeypatch.setattr(oos, "_validate_artifact", lambda output_root, row, **kwargs: results[row["run_id"]])
    monkeypatch.setattr(oos, "_finalization_failure_ids", lambda base: [])
    progress = oos.update_formal_oos_progress(
        output_root=tmp_path, config=config, fingerprints=EXPECTED_FINGERPRINTS,
        orchestrator_sha256="d" * 64,
        source_mechanism_results={case.seed: {"run_id": "source"}},
    )
    assert progress["formal_OOS_gate_passed"] is False
    assert progress["failed_primary_run_ids"] == ["failed"]
    assert progress["duplicate_case_ids"] == [case.case_id]


def test_finalization_exception_writes_bounded_terminal_diagnostic(monkeypatch, tmp_path):
    config = load_formal_extension_config(CONFIG)
    case = oos.build_formal_oos_cases(config)[0]
    monkeypatch.setattr(oos, "load_phase6_matrix", lambda path: {})
    monkeypatch.setattr(
        oos, "capture_runtime_context",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("x" * 20000)),
    )
    with pytest.raises(RuntimeError):
        oos.run_formal_oos_case(
            root=ROOT, output_root=tmp_path,
            matrix_path=ROOT / "configs/phase6_experiment_matrix.yaml",
            config=config, fingerprints=EXPECTED_FINGERPRINTS,
            orchestrator_sha256="d" * 64, locked_environment={},
            source={"commit_sha": "b" * 40, "tree_sha": "c" * 40},
            source_mechanism_results={case.seed: {"run_id": "source"}},
            case=case, run_id="oos_failure", science_executor=lambda **kwargs: {},
        )
    path = tmp_path / oos.OOS_SUBDIRECTORY / "runs/oos_failure/status_summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["status"] == "runner_exception"
    assert summary["current_stage"] == "runtime_context"
    assert len(summary["failure"]["message"]) <= 1000
    assert path.stat().st_size < 16384


def test_status_reader_is_bounded(tmp_path):
    path = tmp_path / "formal_OOS_progress.json"
    path.write_text(json.dumps({
        "status": "incomplete", "required_primary_run_count": 10,
        "completed_primary_run_count": 2, "formal_OOS_gate_passed": False,
        "next_decision": "formal_OOS_incomplete_or_failed",
        "algorithm_performance_authorized": False, "updated_at_utc": "now",
    }), encoding="utf-8")
    summary = _bounded(path)
    assert summary["required_primary_run_count"] == 10
    assert summary["completed_primary_run_count"] == 2
    assert summary["algorithm_performance_authorized"] is False
    assert len(json.dumps(summary).encode("utf-8")) < 16384
