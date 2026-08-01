from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src import phase6_family_runner
from src import phase6_family_worker
from src.phase6_families import _atomic_write_json
from src.phase6_family_runner import (
    _find_e2_source_plan,
    load_family_runner_config,
    resolve_family_pilot_plans,
    run_family_sequence,
)
from src.phase6_family_status import build_family_status
from src.phase6_family_status import MAX_OUTPUT_BYTES, bounded_status_json
from src.phase6_family_worker import _run_e4
from src.phase6_protocol import Phase6ProtocolError, load_phase6_matrix
from src.reproducibility import sha256_file
from src.run_phase6_family import _write_preflight_failure


MATRIX_PATH = Path("configs/phase6_experiment_matrix.yaml").resolve()
CONFIG_PATH = Path("configs/phase6_family_runner.yaml").resolve()
_REAL_LOAD_PHASE6_MATRIX = phase6_family_runner.load_phase6_matrix


@pytest.fixture(autouse=True)
def _freeze_matrix_for_runner_unit_tests(monkeypatch) -> None:
    def load_frozen(path: Path) -> dict[str, Any]:
        matrix = _REAL_LOAD_PHASE6_MATRIX(path)
        matrix["status"] = "frozen_for_formal_execution"
        return matrix

    monkeypatch.setattr(
        phase6_family_runner,
        "load_phase6_matrix",
        load_frozen,
    )


def test_candidate_matrix_blocks_family_pilot_before_plan_resolution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    resolved = False

    def forbidden_resolution(*args, **kwargs):
        nonlocal resolved
        resolved = True
        raise AssertionError("family plans must not resolve")

    monkeypatch.setattr(
        phase6_family_runner,
        "load_phase6_matrix",
        _REAL_LOAD_PHASE6_MATRIX,
    )
    monkeypatch.setattr(
        phase6_family_runner,
        "validate_gurobi_runtime",
        lambda: {"gurobipy": "13.0.2", "optimizer": "13.0.2"},
    )
    monkeypatch.setattr(
        phase6_family_runner,
        "validate_locked_environment",
        lambda _: {"gurobipy": "13.0.2"},
    )
    monkeypatch.setattr(
        phase6_family_runner,
        "resolve_family_pilot_plans",
        forbidden_resolution,
    )
    with pytest.raises(Phase6ProtocolError, match="pilot execution is blocked"):
        run_family_sequence(
            matrix_path=MATRIX_PATH,
            family_config_path=CONFIG_PATH,
            output_root=tmp_path,
            family="E1",
            seed=2026072001,
            execution_mode="pilot",
            run_id="candidate_family_pilot_blocked",
            worker=lambda *args, **kwargs: {},
        )
    assert resolved is False


def test_family_config_is_gurobi_only_and_single_thread(
    tmp_path: Path,
) -> None:
    raw = CONFIG_PATH.read_text(encoding="utf-8")
    bad_solver = tmp_path / "bad_solver.yaml"
    bad_solver.write_text(
        raw.replace("    - gurobi", "    - highs"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exactly \\[gurobi\\]"):
        load_family_runner_config(bad_solver)
    bad_threads = tmp_path / "bad_threads.yaml"
    bad_threads.write_text(
        raw.replace("  threads: 1", "  threads: 2"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Threads=1"):
        load_family_runner_config(bad_threads)


def test_pilot_plan_resolution_is_deterministic_and_bounded() -> None:
    matrix = load_phase6_matrix(MATRIX_PATH)
    matrix["status"] = "frozen_for_formal_execution"
    config = load_family_runner_config(CONFIG_PATH)
    expected = {"E1": 1, "E2": 6, "E4": 1, "E5": 2}
    for family, count in expected.items():
        first = resolve_family_pilot_plans(
            matrix,
            config,
            matrix_path=MATRIX_PATH,
            family=family,
            seed=2026072001,
        )
        second = resolve_family_pilot_plans(
            matrix,
            config,
            matrix_path=MATRIX_PATH,
            family=family,
            seed=2026072001,
        )
        assert first == second
        assert len(first) == count


def _successful_e2_worker(
    request: dict[str, Any],
    timeout_seconds: float,
    work_directory: Path,
) -> dict[str, Any]:
    assert timeout_seconds > 0.0
    policy = request["plan"]["policy"]
    objective = 100.0 if policy == "endogenous_reserve" else 101.0
    path = work_directory / f"{request['plan']['plan_id']}_fake.json"
    payload = {
        "status": "optimal",
        "plan_id": request["plan"]["plan_id"],
        "policy": policy,
        "robust_objective": objective,
        "reserve": 1.0,
        "regular_purchase": {"relief_food_1": [0.0] * 6},
        "exact_training_evaluation": {
            "status": "optimal",
            "infeasible_scenario_count": 0,
            "solver_failure_count": 0,
        },
        "wall_seconds": 0.1,
        "peak_memory_mb": 5.0,
        "result_path": str(path),
    }
    _atomic_write_json(path, payload)
    return payload


def _e2_worker_with_infeasible_deterministic_policy(
    request: dict[str, Any],
    timeout_seconds: float,
    work_directory: Path,
) -> dict[str, Any]:
    payload = _successful_e2_worker(
        request,
        timeout_seconds,
        work_directory,
    )
    policy = request["plan"]["policy"]
    if policy == "deterministic_mean":
        payload["status"] = "unexpected_infeasible_recourse"
        payload["robust_objective"] = None
        payload["exact_training_evaluation"] = {
            "status": "infeasible_recourse",
            "infeasible_scenario_count": 1,
            "solver_failure_count": 0,
        }
        payload["failure"] = {
            "stage": "e2_exact_training_evaluation",
            "message": "relative-complete-recourse invariant violated",
        }
    else:
        payload["exact_training_evaluation"] = {
            "status": "optimal",
            "infeasible_scenario_count": 0,
            "solver_failure_count": 0,
        }
    _atomic_write_json(Path(payload["result_path"]), payload)
    return payload


def test_family_finalization_precedes_registry_and_projection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        phase6_family_runner,
        "validate_gurobi_runtime",
        lambda: {"gurobipy": "13.0.2", "optimizer": "13.0.2"},
    )
    monkeypatch.setattr(
        phase6_family_runner,
        "validate_locked_environment",
        lambda _: {"gurobipy": "13.0.2"},
    )
    events: list[str] = []

    def worker(
        request: dict[str, Any],
        timeout_seconds: float,
        work_directory: Path,
    ) -> dict[str, Any]:
        path = work_directory / "e1_result.json"
        payload = {
            "status": "optimal",
            "plan_id": request["plan"]["plan_id"],
            "robust_objective": 100.0,
            "wall_seconds": min(timeout_seconds, 0.1),
            "peak_memory_mb": 1.0,
            "result_path": str(path),
        }
        _atomic_write_json(path, payload)
        return payload

    def register(output_root: Path, row: dict[str, Any]) -> Path:
        result_path = Path(row["result_path"])
        manifest_path = Path(row["manifest_path"])
        assert result_path.is_file()
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["artifact_state"] == "finalized"
        assert manifest["result_sha256"] == sha256_file(result_path)
        events.append("registry")
        return output_root / "experiments" / "phase6" / "registry.csv"

    def project(**kwargs: Any) -> dict[str, Any]:
        assert events == ["registry"]
        events.append("projection")
        return {
            "status": "projection_incomplete",
            "formal_execution_authorized": False,
        }

    monkeypatch.setattr(
        phase6_family_runner,
        "upsert_family_registry",
        register,
    )
    monkeypatch.setattr(
        phase6_family_runner,
        "update_family_projection",
        project,
    )
    result = run_family_sequence(
        matrix_path=MATRIX_PATH,
        family_config_path=CONFIG_PATH,
        output_root=tmp_path,
        family="E1",
        seed=2026072001,
        execution_mode="pilot",
        run_id="pilot_e1_order",
        worker=worker,
    )
    assert result["status"] == "optimal"
    assert events == ["registry", "projection"]


def test_e2_runner_checkpoints_all_policies_and_checks_dominance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        phase6_family_runner,
        "validate_gurobi_runtime",
        lambda: {"gurobipy": "13.0.2", "optimizer": "13.0.2"},
    )
    monkeypatch.setattr(
        phase6_family_runner,
        "validate_locked_environment",
        lambda _: {"gurobipy": "13.0.2"},
    )
    monkeypatch.setattr(
        phase6_family_runner,
        "_validate_family_pilot_order",
        lambda **_: None,
    )
    result = run_family_sequence(
        matrix_path=MATRIX_PATH,
        family_config_path=CONFIG_PATH,
        output_root=tmp_path,
        family="E2",
        seed=2026072001,
        execution_mode="pilot",
        run_id="pilot_e2_fake",
        worker=_successful_e2_worker,
    )
    assert result["status"] == "optimal"
    assert result["planned_work_units"] == 6
    assert result["completed_work_units"] == 6
    assert {row["status"] for row in result["plans"]} == {"optimal"}
    registry = (
        tmp_path
        / "experiments"
        / "phase6"
        / "family_run_registry.csv"
    ).read_text(encoding="utf-8-sig")
    assert "family_config_sha256" in registry
    run_directory = (
        tmp_path
        / "experiments"
        / "phase6"
        / "family_runs"
        / "pilot_e2_fake"
    )
    manifest = json.loads(
        (run_directory / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["result_sha256"] == sha256_file(
        run_directory / "result.json"
    )
    first_plan = result["plans"][0]
    fingerprints = result["fingerprints"]
    source, source_hash = _find_e2_source_plan(
        output_root=tmp_path,
        source_plan_id=first_plan["plan_id"],
        scientific_hash=fingerprints["scientific_config_sha256"],
        family_config_hash=fingerprints["family_config_sha256"],
        family_code_hash=fingerprints["family_code_sha256"],
        environment_hash=fingerprints["environment_sha256"],
    )
    assert source == Path(first_plan["result_path"])
    assert source_hash == first_plan["result_sha256"]
    source.write_text(
        source.read_text(encoding="utf-8") + " ",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="resolved to 0 artifacts"):
        _find_e2_source_plan(
            output_root=tmp_path,
            source_plan_id=first_plan["plan_id"],
            scientific_hash=fingerprints["scientific_config_sha256"],
            family_config_hash=fingerprints["family_config_sha256"],
            family_code_hash=fingerprints["family_code_sha256"],
            environment_hash=fingerprints["environment_sha256"],
        )


def test_e2_runner_blocks_infeasible_deterministic_evaluation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        phase6_family_runner,
        "validate_gurobi_runtime",
        lambda: {"gurobipy": "13.0.2", "optimizer": "13.0.2"},
    )
    monkeypatch.setattr(
        phase6_family_runner,
        "validate_locked_environment",
        lambda _: {"gurobipy": "13.0.2"},
    )
    monkeypatch.setattr(
        phase6_family_runner,
        "_validate_family_pilot_order",
        lambda **_: None,
    )
    result = run_family_sequence(
        matrix_path=MATRIX_PATH,
        family_config_path=CONFIG_PATH,
        output_root=tmp_path,
        family="E2",
        seed=2026072001,
        execution_mode="pilot",
        run_id="pilot_e2_infeasible_deterministic",
        worker=_e2_worker_with_infeasible_deterministic_policy,
    )
    assert result["status"] == "unexpected_infeasible_recourse"
    assert result["completed_work_units"] == 0
    deterministic = next(
        row
        for row in result["plans"]
        if row["policy"] == "deterministic_mean"
    )
    assert deterministic["status"] == "unexpected_infeasible_recourse"
    assert deterministic["robust_objective"] is None
    assert deterministic["result_sha256"] == sha256_file(
        Path(deterministic["result_path"])
    )
    assert all(
        row["status"] == "not_run_after_family_failure"
        for row in result["plans"][1:]
    )


def test_e2_worker_marks_any_infeasible_policy_as_scientific_error(
    monkeypatch,
) -> None:
    generated = SimpleNamespace(
        tier=SimpleNamespace(id="V2", solver_call_seconds=60.0),
        seed=2026072001,
        budget=100.0,
        data=SimpleNamespace(budget=100.0),
    )
    native = SimpleNamespace(
        regular_purchase={"relief_food_1": [1.0]},
        reserve=0.0,
        objective=90.0,
        model_name="DeterministicMeanModel",
    )
    evaluation = SimpleNamespace(
        status="infeasible_recourse",
        regular_cost=90.0,
        robust_objective=None,
        worst_scenario=None,
        worst_recourse_cost=None,
        scenario_results={
            "s0001": SimpleNamespace(status="infeasible")
        },
        infeasible_scenarios=("s0001",),
        failed_scenarios=(),
        runtime_seconds=0.1,
    )
    monkeypatch.setattr(
        phase6_family_worker,
        "_generate_training",
        lambda request: generated,
    )
    monkeypatch.setattr(
        phase6_family_worker,
        "build_deterministic_model",
        lambda data: object(),
    )
    monkeypatch.setattr(
        phase6_family_worker,
        "solve_model",
        lambda model, **kwargs: native,
    )
    monkeypatch.setattr(
        phase6_family_worker,
        "evaluate_first_stage",
        lambda *args, **kwargs: evaluation,
    )
    result = phase6_family_worker._run_e2(
        {
            "plan": {
                "plan_id": "deterministic_infeasible",
                "policy": "deterministic_mean",
                "budget_index": 1,
            },
            "solver": {
                "preference": ["gurobi"],
                "threads": 1,
                "feasibility_tolerance": 1.0e-7,
                "optimality_tolerance": 1.0e-7,
            },
        }
    )
    assert result["status"] == "unexpected_infeasible_recourse"
    assert result["robust_objective"] is None
    assert (
        result["exact_training_evaluation"]["status"]
        == "infeasible_recourse"
    )
    assert (
        result["exact_training_evaluation"]["infeasible_scenario_count"]
        == 1
    )
    monkeypatch.setattr(
        phase6_family_worker,
        "build_fixed_reserve_model",
        lambda data, ratio: object(),
    )
    fixed = phase6_family_worker._run_e2(
        {
            "plan": {
                "plan_id": "fixed_infeasible",
                "policy": "fixed_reserve_0_10",
                "budget_index": 1,
            },
            "solver": {
                "preference": ["gurobi"],
                "threads": 1,
                "feasibility_tolerance": 1.0e-7,
                "optimality_tolerance": 1.0e-7,
            },
        }
    )
    assert fixed["status"] == "unexpected_infeasible_recourse"


def test_failure_retains_failed_and_not_run_plans(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        phase6_family_runner,
        "validate_gurobi_runtime",
        lambda: {"gurobipy": "13.0.2", "optimizer": "13.0.2"},
    )
    monkeypatch.setattr(
        phase6_family_runner,
        "validate_locked_environment",
        lambda _: {"gurobipy": "13.0.2"},
    )
    monkeypatch.setattr(
        phase6_family_runner,
        "_validate_family_pilot_order",
        lambda **_: None,
    )

    def fail(
        request: dict[str, Any],
        timeout_seconds: float,
        work_directory: Path,
    ) -> dict[str, Any]:
        return {
            "status": "plan_wall_timeout",
            "wall_seconds": timeout_seconds,
            "peak_memory_mb": 1.0,
            "result_path": None,
            "failure": {
                "stage": "external_plan_watchdog",
                "message": "synthetic timeout" + "x" * 100_000,
            },
        }

    result = run_family_sequence(
        matrix_path=MATRIX_PATH,
        family_config_path=CONFIG_PATH,
        output_root=tmp_path,
        family="E5",
        seed=2026072001,
        execution_mode="pilot",
        run_id="pilot_e5_failure",
        worker=fail,
    )
    assert result["status"] == "plan_wall_timeout"
    assert [row["status"] for row in result["plans"]] == [
        "plan_wall_timeout",
        "not_run_after_family_failure",
    ]
    status_path = (
        tmp_path
        / "experiments"
        / "phase6"
        / "family_runs"
        / "pilot_e5_failure"
        / "status_summary.json"
    )
    status_payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert set(status_payload["failure"]) <= {
        "status",
        "stage",
        "message",
        "plan_index",
        "plan_id",
    }
    assert len(status_payload["failure"]["message"]) == 1000
    with pytest.raises(ValueError, match="already started"):
        run_family_sequence(
            matrix_path=MATRIX_PATH,
            family_config_path=CONFIG_PATH,
            output_root=tmp_path,
            family="E5",
            seed=2026072001,
            execution_mode="pilot",
            run_id="pilot_e5_failure",
            worker=fail,
        )


def test_pilot_family_order_is_enforced_before_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        phase6_family_runner,
        "validate_gurobi_runtime",
        lambda: {"gurobipy": "13.0.2", "optimizer": "13.0.2"},
    )
    monkeypatch.setattr(
        phase6_family_runner,
        "validate_locked_environment",
        lambda _: {"gurobipy": "13.0.2"},
    )
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("worker must not start out of family order")

    with pytest.raises(ValueError, match="requires completed predecessors"):
        run_family_sequence(
            matrix_path=MATRIX_PATH,
            family_config_path=CONFIG_PATH,
            output_root=tmp_path,
            family="E2",
            seed=2026072001,
            execution_mode="pilot",
            run_id="pilot_e2_out_of_order",
            worker=forbidden,
        )
    assert called is False


def test_formal_family_gate_blocks_before_plan_resolution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        phase6_family_runner,
        "validate_gurobi_runtime",
        lambda: {"gurobipy": "13.0.2", "optimizer": "13.0.2"},
    )
    monkeypatch.setattr(
        phase6_family_runner,
        "validate_locked_environment",
        lambda _: {"gurobipy": "13.0.2"},
    )
    resolved = False

    def forbidden(*args, **kwargs):
        nonlocal resolved
        resolved = True
        raise AssertionError("formal plans must not resolve before the gate")

    monkeypatch.setattr(
        phase6_family_runner,
        "enumerate_family_plans",
        forbidden,
    )
    with pytest.raises(
        ValueError,
        match="matrix is not frozen|requires a projection",
    ):
        run_family_sequence(
            matrix_path=MATRIX_PATH,
            family_config_path=CONFIG_PATH,
            output_root=tmp_path,
            family="E1",
            tier_id="V1",
            seed=2026072401,
            execution_mode="formal",
            run_id="formal_e1_blocked",
            worker=lambda *args, **kwargs: {},
        )
    assert resolved is False


def test_family_status_never_parses_large_result(
    tmp_path: Path,
) -> None:
    directory = (
        tmp_path
        / "experiments"
        / "phase6"
        / "family_runs"
        / "bounded_status"
    )
    _atomic_write_json(
        directory / "status_summary.json",
        {
            "run_id": "bounded_status",
            "family": "E4",
            "execution_mode": "pilot",
            "status": "running",
            "planned_work_units": 1,
            "completed_work_units": 0,
            "failure": None,
            "updated_at_utc": "2026-07-30T00:00:00+00:00",
        },
    )
    (directory / "result.json").write_text(
        "this is deliberately not valid JSON" * 10000,
        encoding="utf-8",
    )
    payload = build_family_status(tmp_path, "bounded_status")
    assert payload["status"] == "running"
    assert payload["files"]["result"]["size_bytes"] > 100_000
    assert payload["read_error"] is None


@pytest.mark.parametrize(
    ("artifact_name", "status"),
    (
        ("result.json", "optimal"),
        ("result.json", "plan_wall_timeout"),
        ("runner_exception.json", "runner_exception"),
        ("checkpoint.json", "running"),
    ),
)
def test_preflight_failure_never_overwrites_existing_run_state(
    tmp_path: Path,
    artifact_name: str,
    status: str,
) -> None:
    run_id = f"immutable_{artifact_name}_{status}".replace(".", "_")
    directory = (
        tmp_path
        / "experiments"
        / "phase6"
        / "family_runs"
        / run_id
    )
    directory.mkdir(parents=True)
    artifact = directory / artifact_name
    artifact.write_text(
        json.dumps({"status": status, "sentinel": "unchanged"}),
        encoding="utf-8",
    )
    summary = directory / "status_summary.json"
    summary.write_text(
        json.dumps({"status": status, "sentinel": "unchanged"}),
        encoding="utf-8",
    )
    before_artifact = artifact.read_bytes()
    before_summary = summary.read_bytes()
    written = _write_preflight_failure(
        tmp_path,
        run_id=run_id,
        family="E1",
        execution_mode="pilot",
        exc=RuntimeError("must not overwrite"),
    )
    assert written is False
    assert artifact.read_bytes() == before_artifact
    assert summary.read_bytes() == before_summary


def test_preflight_failure_is_itself_an_immutable_terminal_state(
    tmp_path: Path,
) -> None:
    arguments = {
        "run_id": "preflight_terminal",
        "family": "E1",
        "execution_mode": "pilot",
        "exc": RuntimeError("first failure" + "x" * 100_000),
    }
    assert _write_preflight_failure(tmp_path, **arguments) is True
    summary_path = (
        tmp_path
        / "experiments"
        / "phase6"
        / "family_runs"
        / "preflight_terminal"
        / "status_summary.json"
    )
    first = summary_path.read_bytes()
    assert _write_preflight_failure(
        tmp_path,
        **{**arguments, "exc": RuntimeError("second failure")},
    ) is False
    assert summary_path.read_bytes() == first
    payload = json.loads(first)
    assert len(payload["failure"]["message"]) == 1000


def test_status_serialization_is_always_bounded_for_long_failure() -> None:
    payload = {
        "run_id": "r" * 100_000,
        "status": "runner_exception",
        "failure": {
            "status": "runner_exception",
            "stage": "runner_preflight",
            "message": "m" * 1_000_000,
            "partial_repetitions": ["forbidden"] * 10_000,
        },
        "processes": [
            {"pid": index, "name": "p" * 10_000}
            for index in range(100)
        ],
        "files": {
            f"file_{index}": {
                "path": "D:\\" + "x" * 100_000,
                "exists": True,
                "size_bytes": index,
            }
            for index in range(100)
        },
    }
    encoded = bounded_status_json(payload)
    assert len(encoded.encode("utf-8")) <= MAX_OUTPUT_BYTES
    decoded = json.loads(encoded)
    assert "partial_repetitions" not in (decoded.get("failure") or {})
    assert len((decoded.get("failure") or {}).get("message", "")) <= 1000


def test_e4_worker_rechecks_source_hash_before_loading(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        _run_e4(
            {
                "plan": {"source_e2_plan_id": "E2_source"},
                "source_plan_path": str(source),
                "source_plan_sha256": "0" * 64,
            }
        )


def test_e4_worker_blocks_any_unexpected_infeasible_recourse(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.json"
    _atomic_write_json(
        source,
        {
            "status": "optimal",
            "plan_id": "E2_source",
            "regular_purchase": {"item": [1.0]},
            "reserve": 0.0,
        },
    )
    generated = SimpleNamespace(
        tier=SimpleNamespace(id="V2", solver_call_seconds=60.0),
        data=object(),
        budget=100.0,
    )
    monkeypatch.setattr(
        phase6_family_worker,
        "load_phase6_matrix",
        lambda _: {},
    )
    monkeypatch.setattr(
        phase6_family_worker,
        "generate_oos_data",
        lambda *args, **kwargs: generated,
    )
    monkeypatch.setattr(
        phase6_family_worker,
        "evaluate_first_stage",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        phase6_family_worker,
        "aggregate_oos_evaluation",
        lambda *args, **kwargs: {
            "plan_oos_status": "contains_infeasible_recourse",
            "infeasible_scenario_count": 2,
            "solver_failure_count": 0,
        },
    )
    result = _run_e4(
        {
            "plan": {
                "plan_id": "E4_plan",
                "source_e2_plan_id": "E2_source",
                "tier_id": "V2",
                "test_seed": 2036072001,
                "training_seed": 2026072001,
                "budget_index": 1,
                "budget": 100.0,
                "policy": "endogenous_reserve",
            },
            "matrix_path": str(MATRIX_PATH),
            "source_plan_path": str(source),
            "source_plan_sha256": sha256_file(source),
            "solver": {
                "preference": ["gurobi"],
                "threads": 1,
                "feasibility_tolerance": 1.0e-7,
                "optimality_tolerance": 1.0e-7,
            },
        }
    )
    assert result["status"] == "unexpected_infeasible_recourse"
    assert result["failure"]["infeasible_scenario_count"] == 2
