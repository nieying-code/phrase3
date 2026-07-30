from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src import phase6_family_runner
from src.phase6_families import _atomic_write_json
from src.phase6_family_runner import (
    load_family_runner_config,
    resolve_family_pilot_plans,
    run_family_sequence,
)
from src.phase6_family_status import build_family_status
from src.phase6_protocol import Phase6ProtocolError, load_phase6_matrix
from src.reproducibility import sha256_file


MATRIX_PATH = Path("configs/phase6_experiment_matrix.yaml").resolve()
CONFIG_PATH = Path("configs/phase6_family_runner.yaml").resolve()


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
        "wall_seconds": 0.1,
        "peak_memory_mb": 5.0,
        "result_path": str(path),
    }
    _atomic_write_json(path, payload)
    return payload


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
                "message": "synthetic timeout",
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
    with pytest.raises(ValueError, match="terminal result"):
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
    with pytest.raises(Phase6ProtocolError, match="not frozen"):
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
