from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
import yaml

from src.phase6_m2_algorithm_performance import (
    PerformanceCase,
    _objective_tolerance,
    _validate_pilot_result,
    _validate_synchronized_main,
    build_pilot_cases,
    read_status,
    run_sequence,
    update_projection,
    validate_preflight,
    validate_static_freeze,
)
from src.phase6_m2_algorithm_performance_worker import _generated
from src.phase6_m2_algorithm_performance_worker import execute_worker_request
from src.model_data import ProcurementData
from src.phase6_m2 import SupplyDisruptionProfile, apply_regular_supply_disruption
from src.phase6_protocol import GeneratedPhase6Data, TierSpec


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "configs/phase6_m2_algorithm_performance_runner_v1_1.yaml"
APPROVAL = ROOT / "configs/phase6_m2_algorithm_performance_pilot_approval_v1_1.yaml"
AUDIT = ROOT / "docs/handoffs/2026-08-25_phase6_m2_algorithm_performance_runner_fix_authorization_v1_1_audit.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprints() -> dict[str, str]:
    return {
        "scientific_config_sha256": "1" * 64,
        "e3_component_sha256": "2" * 64,
        "family_component_sha256": "3" * 64,
        "runner_config_sha256": "4" * 64,
        "environment_sha256": "5" * 64,
        "algorithm_performance_orchestrator_sha256": "6" * 64,
    }


def _fake_worker(
    calls: list[dict], *, failure_at: int | None = None,
    native="time_limit", exact_count: int = 50,
):
    def execute(request: dict, timeout: float, directory: Path) -> dict:
        calls.append(request)
        if failure_at is not None and len(calls) == failure_at:
            return {"status": native, "solver_status": native, "failure": {"stage": "solver"}}
        profile = request["profile_id"]
        beta = request["beta"]
        scenario_order = [f"scenario_{index:04d}" for index in range(1, 51)]
        scenario_order_sha256 = hashlib.sha256(json.dumps(
            scenario_order, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()).hexdigest()
        components = {
            "latent_draw_sha256": "a" * 64,
            "demand_sha256": "b" * 64,
            "fulfillment_sha256": ("c" if profile == "C0" else "d") * 64,
            "emergency_price_sha256": "e" * 64,
            "emergency_supply_sha256": "f" * 64,
            "scenario_order_sha256": scenario_order_sha256,
        }
        ccg = {
            "objective": 100.0 + beta,
            "exact_scenario_costs": {
                name: float(index)
                for index, name in enumerate(scenario_order[:exact_count])
            },
            "iteration_log": [{"added_scenario": scenario_order[1], "added_type": "worst_cost"}],
            "worst_scenario": scenario_order[1],
            "final_scenario_set": scenario_order,
            "iterations": 1,
        }
        prior = request.get("previous_state")
        reusable = set() if prior is None else (
            set(prior["active_scenarios"]) | set(prior["historical_adversarial_scenarios"])
        )
        initial = scenario_order[:1] if prior is None else [name for name in scenario_order if name in reusable or name == scenario_order[0]]
        canonical = None if prior is None else hashlib.sha256(json.dumps(
            prior, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()).hexdigest()
        transferred = [name for name in initial if name in reusable]
        active_or_worst = [
            name for name in transferred
            if name == scenario_order[-1] or name == ccg["worst_scenario"]
        ]
        return {
            "status": "optimal", "solver_status": "optimal",
            "algorithm": request["algorithm"], "objective": 100.0 + beta,
            "joint_scenario_set_sha256": ("7" if profile == "C0" else "8") * 64,
            "component_set_sha256": components,
            "scenario_count": 50,
            "initial_scenarios": initial,
            "initial_scenario_pool_size": len(initial),
            "transfer_source_state_sha256": canonical,
            "transfer_source_budget": None if prior is None else prior["budget"],
            "transferred_exact_scenarios": transferred,
            "transferred_exact_scenario_count": len(transferred),
            "transferred_scenario_reuse_rate": 0.0 if not initial else len(transferred) / len(initial),
            "transferred_scenarios_becoming_active_or_worst": active_or_worst,
            "transferred_scenarios_becoming_active_or_worst_count": len(active_or_worst),
            "ccg_result": ccg if request["algorithm"] != "extensive" else None,
            "scientific_result": ccg, "subprocess_wall_seconds": 1.0,
            "sampled_peak_RSS_MiB": 10.0, "failure": None,
        }
    return execute


def test_frozen_matrix_is_exact_and_formal_remains_closed() -> None:
    context = validate_static_freeze(ROOT, RUNNER, APPROVAL)
    design = context["design"]
    cases = build_pilot_cases(design)
    assert [(row.seed, row.profile_id) for row in cases] == [
        (seed, profile)
        for seed in (2026091001, 2026091002, 2026091003)
        for profile in ("C0", "T03")
    ]
    assert design["pilot_protocol"]["planned_algorithm_solve_count"] == 36
    assert design["formal_matrix"]["planned_algorithm_execution_count"] == 240
    assert context["runner"]["execution"]["formal_execution_implemented"] is False
    assert context["runner"]["execution"]["formal_authorized"] is False
    assert context["runner"]["namespace"] == "phase6_m2_algorithm_performance_v1_1"
    assert context["runner"]["output_root"] == "outputs/phase6_m2_algorithm_performance_v1_1"
    assert not (ROOT / context["runner"]["output_root"]).exists()


def test_audit_locks_runner_artifacts_fingerprints_and_zero_execution() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    paths = {
        "design_config_sha256": ROOT / "configs/phase6_m2_algorithm_performance_design_v1_0.yaml",
        "runner_config_sha256": RUNNER,
        "approval_sha256": APPROVAL,
        "orchestrator_module_sha256": ROOT / "src/phase6_m2_algorithm_performance.py",
        "worker_module_sha256": ROOT / "src/phase6_m2_algorithm_performance_worker.py",
        "cli_sha256": ROOT / "src/run_phase6_m2_algorithm_performance.py",
        "status_module_sha256": ROOT / "src/phase6_m2_algorithm_performance_status.py",
    }
    current_artifacts = {field: _sha(path) for field, path in paths.items()}
    assert current_artifacts == audit["artifacts"]
    assert approval["approved_fingerprints"] == audit["fingerprints"]
    assert approval["artifact_sha256"] == {
        "runner_config": audit["artifacts"]["runner_config_sha256"],
        "orchestrator_module": audit["artifacts"]["orchestrator_module_sha256"],
        "worker_module": audit["artifacts"]["worker_module_sha256"],
        "cli": audit["artifacts"]["cli_sha256"],
        "status_module": audit["artifacts"]["status_module_sha256"],
    }
    assert audit["authorization"] == {
        "approval_status": "frozen_for_pilot_execution",
        "pilot_authorized": True,
        "explicit_cli_authorization_required": True,
        "reviewed_runner_fix_commit": "03978b0efce768672233079ea23364c6ca632418",
        "formal_authorized": False,
        "M0_E3_additional_runs_authorized": False,
        "M2_mechanism_additional_runs_authorized": False,
        "M2_OOS_additional_runs_authorized": False,
        "M2_1_additional_runs_authorized": False,
    }
    assert all(value == 0 for value in audit["execution_counts"].values())
    assert approval["reviewed_runner_merge_commit"] == audit["base"]["reviewed_runner_fix_commit"]
    assert audit["safety"]["old_failed_evidence_is_immutable_and_excluded"] is True
    assert audit["safety"]["new_output_root_must_be_absent_or_empty"] is True
    assert audit["safety"]["execution_requires_main_tracking_origin_main"] is True
    assert audit["safety"]["execution_requires_HEAD_equal_fetched_origin_main"] is True
    assert audit["safety"]["execution_requires_reviewed_runner_fix_commit_ancestor"] is True
    assert audit["safety"]["ordered_oracle_scenario_keys_bound_to_scenario_order_sha256"] is True
    assert audit["safety"]["second_budget_transfer_recomputed_from_prior_state_and_must_be_nonempty"] is True


def test_pending_approval_rejects_before_runtime_or_generation(monkeypatch, tmp_path) -> None:
    called = False
    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("runtime preflight must not run")
    monkeypatch.setattr("src.phase6_m2_algorithm_performance.validate_gurobi_runtime", forbidden)
    pending = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    pending["status"] = "runner_frozen_pilot_pending_authorization"
    pending["pilot_authorized"] = False
    pending["reviewed_runner_merge_commit"] = None
    pending_path = tmp_path / "pending_approval.yaml"
    pending_path.write_text(yaml.safe_dump(pending, sort_keys=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="not authorized"):
        validate_preflight(ROOT, RUNNER, pending_path, require_authorization=True)
    assert called is False


def test_synchronized_main_is_read_only_and_requires_reviewed_merge(monkeypatch) -> None:
    head = "1" * 40
    merge_commit = "2" * 40
    values = {
        ("branch", "--show-current"): "main",
        ("config", "--get", "branch.main.remote"): "origin",
        ("config", "--get", "branch.main.merge"): "refs/heads/main",
        ("rev-parse", "HEAD"): head,
        ("rev-parse", "refs/remotes/origin/main"): head,
        ("rev-parse", "HEAD^{tree}"): "3" * 40,
        ("merge-base", "--is-ancestor", merge_commit, head): "",
    }
    monkeypatch.setattr(
        "src.phase6_m2_algorithm_performance._git",
        lambda root, *args: values[args],
    )
    identity = _validate_synchronized_main(ROOT, reviewed_runner_merge_commit=merge_commit)
    assert identity == {
        "branch": "main", "upstream_remote": "origin",
        "upstream_merge": "refs/heads/main", "head": head,
        "remote_main": head, "tree": "3" * 40,
        "reviewed_runner_merge_commit": merge_commit,
    }


def test_synchronized_main_rejects_unsynchronized_or_missing_reviewed_merge(monkeypatch) -> None:
    with pytest.raises(RuntimeError, match="missing or invalid"):
        _validate_synchronized_main(ROOT, reviewed_runner_merge_commit="")
    head = "1" * 40
    values = {
        ("branch", "--show-current"): "main",
        ("config", "--get", "branch.main.remote"): "origin",
        ("config", "--get", "branch.main.merge"): "refs/heads/main",
        ("rev-parse", "HEAD"): head,
        ("rev-parse", "refs/remotes/origin/main"): "4" * 40,
    }
    monkeypatch.setattr(
        "src.phase6_m2_algorithm_performance._git",
        lambda root, *args: values[args],
    )
    with pytest.raises(RuntimeError, match="synchronized"):
        _validate_synchronized_main(ROOT, reviewed_runner_merge_commit="2" * 40)


def test_synchronized_main_rejects_unreviewed_head(monkeypatch) -> None:
    head = "1" * 40
    merge_commit = "2" * 40
    values = {
        ("branch", "--show-current"): "main",
        ("config", "--get", "branch.main.remote"): "origin",
        ("config", "--get", "branch.main.merge"): "refs/heads/main",
        ("rev-parse", "HEAD"): head,
        ("rev-parse", "refs/remotes/origin/main"): head,
    }
    def fake_git(root, *args):
        if args[0] == "merge-base":
            raise subprocess.CalledProcessError(1, args)
        return values[args]
    monkeypatch.setattr("src.phase6_m2_algorithm_performance._git", fake_git)
    with pytest.raises(RuntimeError, match="not an ancestor"):
        _validate_synchronized_main(ROOT, reviewed_runner_merge_commit=merge_commit)


def test_sequence_executes_frozen_order_and_transfers_first_budget_pool(tmp_path) -> None:
    context = validate_static_freeze(ROOT, RUNNER, APPROVAL)
    calls: list[dict] = []
    result = run_sequence(
        root=ROOT, runner=context["runner"], design=context["design"],
        fingerprints=_fingerprints(),
        case=PerformanceCase("case", 2026091001, "T03"), run_id="pilot_case",
        execution_root=tmp_path, worker_executor=_fake_worker(calls),
    )
    assert result["status"] == "optimal"
    assert [row["algorithm"] for row in calls] == [
        "extensive", "cold", "warm", "extensive", "warm", "cold"
    ]
    assert calls[2]["previous_state"] is None
    assert calls[4]["previous_state"]["budget"] == 2571.372016574617
    assert calls[4]["previous_state"]["historical_adversarial_scenarios"] == ["scenario_0002"]
    second_warm = result["comparisons"][1]["methods"]["warm"]
    assert second_warm["transferred_exact_scenarios"] == [
        "scenario_0002", "scenario_0050",
    ]
    assert second_warm["transferred_scenarios_becoming_active_or_worst"] == [
        "scenario_0002", "scenario_0050",
    ]
    assert result["completed_algorithm_solve_count"] == 6
    assert all(row["maximum_objective_difference"] == 0.0 for row in result["comparisons"])
    manifest = json.loads((tmp_path / "runs/pilot_case/manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact_state"] == "finalized"


@pytest.mark.parametrize("native", ["time_limit", "master_time_limit"])
def test_native_timeout_is_terminal_and_stops_sequence(tmp_path, native) -> None:
    context = validate_static_freeze(ROOT, RUNNER, APPROVAL)
    calls: list[dict] = []
    with pytest.raises(RuntimeError):
        run_sequence(
            root=ROOT, runner=context["runner"], design=context["design"],
            fingerprints=_fingerprints(), case=PerformanceCase("case", 2026091001, "C0"),
            run_id=f"timeout_{native}", execution_root=tmp_path,
            worker_executor=_fake_worker(calls, failure_at=1, native=native),
        )
    assert len(calls) == 1
    status = json.loads((tmp_path / f"runs/timeout_{native}/status_summary.json").read_text(encoding="utf-8"))
    assert status["status"] == "timeout"


def test_incomplete_exact_oracle_stops_before_next_method(tmp_path) -> None:
    context = validate_static_freeze(ROOT, RUNNER, APPROVAL)
    calls: list[dict] = []
    with pytest.raises(ValueError, match="exact oracle"):
        run_sequence(
            root=ROOT, runner=context["runner"], design=context["design"],
            fingerprints=_fingerprints(), case=PerformanceCase("case", 2026091001, "C0"),
            run_id="incomplete_oracle", execution_root=tmp_path,
            worker_executor=_fake_worker(calls, exact_count=49),
        )
    # EF has no C&CG exact-cost mapping; the first cold call is rejected and warm is not started.
    assert [row["algorithm"] for row in calls] == ["extensive", "cold"]


def test_oracle_count_cannot_hide_wrong_ordered_scenario_identities(tmp_path) -> None:
    context = validate_static_freeze(ROOT, RUNNER, APPROVAL)
    result = run_sequence(
        root=ROOT, runner=context["runner"], design=context["design"],
        fingerprints=_fingerprints(), case=PerformanceCase("case", 1, "C0"),
        run_id="wrong_oracle", execution_root=tmp_path,
        worker_executor=_fake_worker([]),
    )
    result["comparisons"][0]["methods"]["cold"]["ccg_result"]["exact_scenario_costs"] = {
        f"wrong_{index:04d}": float(index) for index in range(1, 51)
    }
    with pytest.raises(ValueError, match="scenario identities"):
        _validate_pilot_result(
            result, PerformanceCase("case", 1, "C0"), _fingerprints(), None,
        )


def test_second_budget_cannot_claim_empty_cross_budget_transfer(tmp_path) -> None:
    context = validate_static_freeze(ROOT, RUNNER, APPROVAL)
    result = run_sequence(
        root=ROOT, runner=context["runner"], design=context["design"],
        fingerprints=_fingerprints(), case=PerformanceCase("case", 1, "T03"),
        run_id="empty_transfer", execution_root=tmp_path,
        worker_executor=_fake_worker([]),
    )
    warm = result["comparisons"][1]["methods"]["warm"]
    warm["transferred_exact_scenarios"] = []
    warm["transferred_exact_scenario_count"] = 0
    warm["transferred_scenario_reuse_rate"] = 0.0
    warm["transferred_scenarios_becoming_active_or_worst"] = []
    warm["transferred_scenarios_becoming_active_or_worst_count"] = 0
    with pytest.raises(ValueError, match="empty or differ"):
        _validate_pilot_result(
            result, PerformanceCase("case", 1, "T03"), _fingerprints(), None,
        )


def test_projection_recomputes_crn_as_a_hard_gate(tmp_path) -> None:
    context = validate_static_freeze(ROOT, RUNNER, APPROVAL)
    cases = tuple(
        PerformanceCase(f"s{seed}_{profile}", seed, profile)
        for seed in (1, 2, 3) for profile in ("C0", "T03")
    )
    rows = []
    for case in cases:
        calls: list[dict] = []
        run_id = f"run_{case.case_id}"
        run_sequence(
            root=ROOT, runner=context["runner"], design=context["design"],
            fingerprints=_fingerprints(), case=case, run_id=run_id,
            execution_root=tmp_path, worker_executor=_fake_worker(calls),
        )
        rows.append({"run_id": run_id, "parent_run_id": None, "case_id": case.case_id, "status": "optimal"})
    (tmp_path / "run_registry.json").write_text(json.dumps({"runs": rows}), encoding="utf-8")
    complete = update_projection(tmp_path, cases, _fingerprints())
    assert complete["pilot_compute_gate_passed"] is True
    assert complete["completed_budget_pair_count"] == 12
    assert complete["completed_algorithm_solve_count"] == 36
    assert len(complete["cross_budget_transfer_evidence"]) == 6
    assert complete["total_transferred_exact_scenario_count"] == 12
    assert complete["total_transferred_scenarios_becoming_active_or_worst_count"] == 12
    assert complete["formal_compute_projection"] == {
        "status": "projected",
        "method": "240_times_maximum_pilot_CCG_worker_seconds",
        "planned_formal_algorithm_execution_count": 240,
        "conservative_seconds_per_execution": 1.0,
        "projected_wall_hours": 1.0 / 15.0,
        "maximum_sampled_peak_RSS_MiB": 10.0,
    }
    tampered = tmp_path / "runs/run_s2_T03/result.json"
    payload = json.loads(tampered.read_text(encoding="utf-8"))
    for comparison in payload["comparisons"]:
        for method in comparison["methods"].values():
            method["component_set_sha256"]["latent_draw_sha256"] = "0" * 64
    tampered.write_text(json.dumps(payload), encoding="utf-8")
    manifest = tampered.with_name("manifest.json")
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["result_sha256"] = _sha(tampered)
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    projection = update_projection(tmp_path, cases, _fingerprints())
    assert projection["pilot_compute_gate_passed"] is False
    assert projection["common_random_number_mismatches"] == [
        {"seed": 2, "budget_index": 0, "field": "latent_draw_sha256"},
        {"seed": 2, "budget_index": 1, "field": "latent_draw_sha256"},
    ]
    assert projection["formal_authorized"] is False


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, -1.0])
def test_objective_consistency_rejects_nonfinite_or_negative_tolerances(bad) -> None:
    with pytest.raises(ValueError, match="finite and nonnegative"):
        _objective_tolerance([30000.0], {"absolute_tolerance": bad, "relative_tolerance": 1.0e-7})
    with pytest.raises(ValueError, match="finite and nonnegative"):
        _objective_tolerance([30000.0], {"absolute_tolerance": 1.0e-5, "relative_tolerance": bad})


def test_frozen_m2_objective_tolerance_boundary_is_exact() -> None:
    assert math.isclose(
        _objective_tolerance([30000.0, 30000.00301], {
            "absolute_tolerance": 1.0e-5, "relative_tolerance": 1.0e-7,
        }),
        0.003010000301,
        rel_tol=0.0, abs_tol=1.0e-15,
    )


def test_generated_resolves_and_passes_profile_without_real_generation(monkeypatch, tmp_path) -> None:
    design = yaml.safe_load((ROOT / "configs/phase6_m2_algorithm_performance_design_v1_0.yaml").read_text(encoding="utf-8"))
    design_path = tmp_path / "design.yaml"
    design_path.write_text(yaml.safe_dump(design), encoding="utf-8")
    base = SimpleNamespace(data=SimpleNamespace(storage_capacity=(1.0,) * 6))
    generated = object()
    profile = object()
    monkeypatch.setattr("src.phase6_m2_algorithm_performance_worker.load_phase6_matrix", lambda path: {})
    monkeypatch.setattr("src.phase6_m2_algorithm_performance_worker._confirmation_config", lambda root: {})
    monkeypatch.setattr("src.phase6_m2_algorithm_performance_worker._validate_formal_baseline_before_generation", lambda *args, **kwargs: ({}, 10.0, 11.0, (1.0,) * 6))
    monkeypatch.setattr("src.phase6_m2_algorithm_performance_worker.generate_phase6_data", lambda *args, **kwargs: base)
    monkeypatch.setattr("src.phase6_m2_algorithm_performance_worker.reconstruct_frozen_demand_latent", lambda *args: "latent")
    monkeypatch.setattr("src.phase6_m2_algorithm_performance_worker._science_config_for_formal", lambda *args: {"profiles": "frozen"})
    monkeypatch.setattr("src.phase6_m2.resolve_supply_disruption_profile", lambda config, profile_id: profile)
    observed = {}
    def apply(base_arg, **kwargs):
        observed.update(kwargs)
        return generated
    monkeypatch.setattr("src.phase6_m2_algorithm_performance_worker.apply_m2c2_supply_disruption", apply)
    result, reference, returned_profile = _generated({
        "project_root": str(ROOT), "matrix_path": str(ROOT / "configs/phase6_experiment_matrix.yaml"),
        "design_path": str(design_path), "beta": 1.1, "scenario_count": 50,
        "seed": 2026091001, "profile_id": "T03",
    })
    assert result is generated and reference == 10.0
    assert returned_profile is profile
    assert observed["profile"] is profile


def test_real_disrupted_data_wrapper_exposes_budget_through_worker_result(monkeypatch) -> None:
    base = ProcurementData(
        items=("food",), periods=2, scenarios=("low", "high"), budget=17.5,
        shelf_life={"food": 2}, initial_inventory={"food": (1.0, 0.0)},
        storage_capacity=(20.0, 20.0), regular_price={"food": (1.0, 1.0)},
        demand={"low": {"food": (2.0, 2.0)}, "high": {"food": (5.0, 5.0)}},
        emergency_price={"low": {"food": (2.0, 2.0)}, "high": {"food": (2.0, 2.0)}},
        emergency_supply={"low": {"food": (10.0, 10.0)}, "high": {"food": (10.0, 10.0)}},
        shortage_penalty={"food": 20.0}, waste_penalty={"food": 1.0},
    )
    generated = GeneratedPhase6Data(
        data=base,
        tier=TierSpec("V1", 1, 2, 2, 0, 0, "none", 120.0, 600.0, 1800.0, 1),
        seed=1, budget=base.budget, reference_budget=base.budget,
        budget_factor=1.0, theoretical_mean_demand={"food": (3.5, 3.5)},
        generator_protocol_id="wrapper-interface-test",
    )
    latent = {
        "low": {"food": (-1.0, -0.5)},
        "high": {"food": (1.0, 1.5)},
    }
    wrapped = apply_regular_supply_disruption(
        generated, SupplyDisruptionProfile("C0", False, 0.0, 0.0),
        demand_latent=latent,
    )
    fake_solution = SimpleNamespace(
        objective=12.0,
        as_dict=lambda: {"status": "optimal", "objective": 12.0},
    )
    monkeypatch.setattr(
        "src.phase6_m2_algorithm_performance_worker._generated",
        lambda request: (wrapped, base.budget, wrapped.profile),
    )
    monkeypatch.setattr(
        "src.phase6_m2_algorithm_performance_worker.solve_m2_endogenous_extensive",
        lambda *args, **kwargs: fake_solution,
    )
    monkeypatch.setattr(
        "src.phase6_m2_algorithm_performance_worker._native_failure_status",
        lambda result: "optimal",
    )
    result = execute_worker_request({
        "algorithm": "extensive", "seed": 1, "profile_id": "C0",
        "beta": 1.1, "solver": {
            "preference": ["gurobi"], "call_time_limit_seconds": 120,
            "threads": 1, "feasibility_tolerance": 1.0e-7,
            "optimality_tolerance": 1.0e-7,
        },
        "ccg": {"active_scenario_tolerance": 1.0e-6},
        "objective_consistency": {"absolute_tolerance": 1.0e-5},
    })
    assert type(wrapped.data).__name__ == "DisruptedProcurementData"
    assert not hasattr(wrapped.data, "total_budget")
    assert result["status"] == "optimal"
    assert result["budget"] == wrapped.data.budget == 17.5


def test_status_reader_is_bounded_and_run_ids_are_safe(tmp_path) -> None:
    path = tmp_path / "status.json"
    path.write_text('{"status":"optimal"}', encoding="utf-8")
    assert read_status(path)["status"] == "optimal"
    path.write_text("x" * 17000, encoding="utf-8")
    with pytest.raises(ValueError, match="bounded"):
        read_status(path)
