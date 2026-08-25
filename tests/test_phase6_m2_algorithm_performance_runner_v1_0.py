from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest
import yaml

from src.phase6_m2_algorithm_performance import (
    PerformanceCase,
    build_pilot_cases,
    read_status,
    run_sequence,
    update_projection,
    validate_preflight,
    validate_static_freeze,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "configs/phase6_m2_algorithm_performance_runner_v1_0.yaml"
APPROVAL = ROOT / "configs/phase6_m2_algorithm_performance_pilot_approval_v1_0.yaml"
AUDIT = ROOT / "docs/handoffs/2026-08-25_phase6_m2_algorithm_performance_runner_v1_0_audit.json"


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


def _fake_worker(calls: list[dict], *, failure_at: int | None = None, native="time_limit"):
    def execute(request: dict, timeout: float, directory: Path) -> dict:
        calls.append(request)
        if failure_at is not None and len(calls) == failure_at:
            return {"status": native, "solver_status": native, "failure": {"stage": "solver"}}
        profile = request["profile_id"]
        beta = request["beta"]
        scenario_order = ["scenario_0001", "scenario_0002"]
        components = {
            "latent_draw_sha256": "a" * 64,
            "demand_sha256": "b" * 64,
            "fulfillment_sha256": ("c" if profile == "C0" else "d") * 64,
            "emergency_price_sha256": "e" * 64,
            "emergency_supply_sha256": "f" * 64,
            "scenario_order_sha256": "9" * 64,
        }
        ccg = {
            "objective": 100.0 + beta,
            "exact_scenario_costs": {scenario_order[0]: 5.0, scenario_order[1]: 7.0},
            "iteration_log": [{"added_scenario": scenario_order[1], "added_type": "worst_cost"}],
            "worst_scenario": scenario_order[1],
            "final_scenario_set": scenario_order,
            "iterations": 1,
        }
        return {
            "status": "optimal", "solver_status": "optimal",
            "algorithm": request["algorithm"], "objective": 100.0 + beta,
            "joint_scenario_set_sha256": ("7" if profile == "C0" else "8") * 64,
            "component_set_sha256": components,
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
    assert {field: _sha(path) for field, path in paths.items()} == audit["artifacts"]
    assert approval["approved_fingerprints"] == audit["fingerprints"]
    assert approval["artifact_sha256"] == {
        "runner_config": audit["artifacts"]["runner_config_sha256"],
        "orchestrator_module": audit["artifacts"]["orchestrator_module_sha256"],
        "worker_module": audit["artifacts"]["worker_module_sha256"],
        "cli": audit["artifacts"]["cli_sha256"],
        "status_module": audit["artifacts"]["status_module_sha256"],
    }
    assert audit["authorization"] == {
        "pilot_authorized": False, "formal_authorized": False,
        "other_tracks_authorized": False,
    }
    assert all(value == 0 for value in audit["execution_counts"].values())


def test_pending_approval_rejects_before_runtime_or_generation(monkeypatch) -> None:
    called = False
    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("runtime preflight must not run")
    monkeypatch.setattr("src.phase6_m2_algorithm_performance.validate_gurobi_runtime", forbidden)
    with pytest.raises(RuntimeError, match="not authorized"):
        validate_preflight(ROOT, RUNNER, APPROVAL, require_authorization=True)
    assert called is False


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


def _write_final_run(root: Path, case: PerformanceCase, *, crn: str) -> dict:
    run_id = f"run_{case.case_id}"
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True)
    methods = {
        name: {
            "component_set_sha256": {
                "latent_draw_sha256": crn, "demand_sha256": "b" * 64,
                "fulfillment_sha256": ("c" if case.profile_id == "C0" else "d") * 64,
                "emergency_price_sha256": "e" * 64,
                "emergency_supply_sha256": "f" * 64, "scenario_order_sha256": "9" * 64,
            }
        }
        for name in ("extensive", "cold", "warm")
    }
    result = {
        "artifact_state": "finalized", "status": "optimal", "run_id": run_id,
        "case_id": case.case_id, "seed": case.seed, "profile_id": case.profile_id,
        "completed_algorithm_solve_count": 6, "fingerprints": _fingerprints(),
        "comparisons": [{"methods": methods}, {"methods": methods}],
    }
    result_path = run_dir / "result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    import hashlib
    sha = hashlib.sha256(result_path.read_bytes()).hexdigest()
    (run_dir / "manifest.json").write_text(json.dumps({"result_sha256": sha}), encoding="utf-8")
    return {"run_id": run_id, "parent_run_id": None, "case_id": case.case_id, "status": "optimal"}


def test_projection_recomputes_crn_as_a_hard_gate(tmp_path) -> None:
    cases = tuple(
        PerformanceCase(f"s{seed}_{profile}", seed, profile)
        for seed in (1, 2, 3) for profile in ("C0", "T03")
    )
    rows = [_write_final_run(tmp_path, case, crn=("a" * 64 if not (case.seed == 2 and case.profile_id == "T03") else "0" * 64)) for case in cases]
    (tmp_path / "run_registry.json").write_text(json.dumps({"runs": rows}), encoding="utf-8")
    projection = update_projection(tmp_path, cases, _fingerprints())
    assert projection["pilot_compute_gate_passed"] is False
    assert projection["common_random_number_mismatches"] == [
        {"seed": 2, "budget_index": 0, "field": "latent_draw_sha256"},
        {"seed": 2, "budget_index": 1, "field": "latent_draw_sha256"},
    ]
    assert projection["formal_authorized"] is False


def test_status_reader_is_bounded_and_run_ids_are_safe(tmp_path) -> None:
    path = tmp_path / "status.json"
    path.write_text('{"status":"optimal"}', encoding="utf-8")
    assert read_status(path)["status"] == "optimal"
    path.write_text("x" * 17000, encoding="utf-8")
    with pytest.raises(ValueError, match="bounded"):
        read_status(path)
