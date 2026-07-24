from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

import pytest

import src.run_phase5 as run_phase5_module
import src.spw_ccg as spw_ccg_module
from src.run_phase5 import run


def test_formal_phase5_run_writes_complete_outputs(tmp_path: Path) -> None:
    payload = run(Path("configs/phase5.yaml"), tmp_path)

    assert payload["status"] == "optimal"
    assert payload["budgets"] == [
        700.0,
        800.0,
        900.0,
        1000.0,
        1100.0,
        1200.0,
    ]
    assert len(payload["comparisons"]) == 6
    assert payload["total_iteration_reduction"] == 13
    assert all(
        row["objectives_consistent"] for row in payload["comparisons"]
    )
    assert max(
        row["objective_difference"] for row in payload["comparisons"]
    ) == pytest.approx(0.0)
    assert payload["comparisons"][-1]["warm_result"]["reserve"] == pytest.approx(
        149.0446500844194,
        abs=1.0e-6,
    )

    solution_path = (
        tmp_path / "solutions" / "phase5" / "spw_ccg_results.json"
    )
    comparison_path = (
        tmp_path / "tables" / "phase5" / "budget_comparison.csv"
    )
    transfer_path = (
        tmp_path / "tables" / "phase5" / "scenario_pool_transfer.csv"
    )
    iteration_path = (
        tmp_path / "logs" / "phase5" / "ccg_iterations.csv"
    )
    for path in (
        solution_path,
        comparison_path,
        transfer_path,
        iteration_path,
    ):
        assert path.is_file()
        assert path.stat().st_size > 0

    written_payload = json.loads(solution_path.read_text(encoding="utf-8"))
    assert written_payload["status"] == "optimal"
    assert written_payload["budgets"] == payload["budgets"]

    with comparison_path.open(encoding="utf-8-sig", newline="") as handle:
        comparison_rows = list(csv.DictReader(handle))
    assert len(comparison_rows) == 6
    assert {
        "budget",
        "cold_objective",
        "warm_objective",
        "objective_difference",
        "cold_iterations",
        "warm_iterations",
        "warm_reserve",
    } <= set(comparison_rows[0])

    with transfer_path.open(encoding="utf-8-sig", newline="") as handle:
        transfer_rows = list(csv.DictReader(handle))
    assert len(transfer_rows) == 6 * 20

    with iteration_path.open(encoding="utf-8-sig", newline="") as handle:
        iteration_rows = list(csv.DictReader(handle))
    assert iteration_rows
    assert {row["mode"] for row in iteration_rows} == {"cold", "warm"}


def test_failed_budget_writes_partial_diagnostics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original = run_phase5_module.run_spw_ccg_budget_sequence

    def force_max_iteration_failure(data, budgets, **kwargs):
        kwargs["max_iterations"] = 1
        return original(data, (700.0, 800.0), **kwargs)

    monkeypatch.setattr(
        run_phase5_module,
        "run_spw_ccg_budget_sequence",
        force_max_iteration_failure,
    )

    payload = run(Path("configs/phase5.yaml"), tmp_path)

    assert payload["status"] == "warm_max_iterations"
    assert payload["completed_budget_count"] == 1
    assert payload["failure"]["budget"] == 800.0
    assert payload["failure"]["stage"] == "warm"
    assert payload["failure"]["warm_result"]["termination_status"] == (
        "max_iterations"
    )
    assert payload["failure"]["warm_result"]["iteration_log"]

    solution_path = (
        tmp_path / "solutions" / "phase5" / "spw_ccg_results.json"
    )
    comparison_path = (
        tmp_path / "tables" / "phase5" / "budget_comparison.csv"
    )
    transfer_path = (
        tmp_path / "tables" / "phase5" / "scenario_pool_transfer.csv"
    )
    iteration_path = (
        tmp_path / "logs" / "phase5" / "ccg_iterations.csv"
    )
    for path in (
        solution_path,
        comparison_path,
        transfer_path,
        iteration_path,
    ):
        assert path.is_file()
        assert path.stat().st_size > 0

    written_payload = json.loads(solution_path.read_text(encoding="utf-8"))
    assert written_payload["status"] == "warm_max_iterations"

    with comparison_path.open(encoding="utf-8-sig", newline="") as handle:
        comparison_rows = list(csv.DictReader(handle))
    assert len(comparison_rows) == 2
    assert comparison_rows[-1]["status"] == "warm_max_iterations"
    assert comparison_rows[-1]["failure_stage"] == "warm"

    with iteration_path.open(encoding="utf-8-sig", newline="") as handle:
        iteration_rows = list(csv.DictReader(handle))
    assert any(
        row["budget"] == "800.0" and row["mode"] == "warm"
        for row in iteration_rows
    )


def test_unexpected_runner_error_still_writes_diagnostics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def raise_unexpected_error(*args, **kwargs):
        raise RuntimeError("synthetic runner failure")

    monkeypatch.setattr(
        run_phase5_module,
        "run_spw_ccg_budget_sequence",
        raise_unexpected_error,
    )

    payload = run(Path("configs/phase5.yaml"), tmp_path)

    assert payload["status"] == "runner_exception"
    assert payload["failure"]["exception_type"] == "RuntimeError"
    assert payload["failure"]["message"] == "synthetic runner failure"
    assert (
        tmp_path / "solutions" / "phase5" / "spw_ccg_results.json"
    ).is_file()
    for relative_path in (
        Path("tables/phase5/budget_comparison.csv"),
        Path("tables/phase5/scenario_pool_transfer.csv"),
        Path("logs/phase5/ccg_iterations.csv"),
    ):
        lines = (tmp_path / relative_path).read_text(
            encoding="utf-8-sig"
        ).splitlines()
        assert len(lines) == 1


def test_missing_config_still_writes_minimum_diagnostics(
    tmp_path: Path,
) -> None:
    payload = run(tmp_path / "missing.yaml", tmp_path / "outputs")

    assert payload["status"] == "runner_exception"
    assert payload["completed_budget_count"] == 0
    assert payload["comparisons"] == []
    assert payload["failure"]["stage"] == "config_load"
    assert payload["failure"]["exception_type"] == "FileNotFoundError"

    output_root = tmp_path / "outputs"
    solution_path = (
        output_root / "solutions" / "phase5" / "spw_ccg_results.json"
    )
    assert solution_path.is_file()
    written_payload = json.loads(solution_path.read_text(encoding="utf-8"))
    assert written_payload["status"] == "runner_exception"
    for relative_path in (
        Path("tables/phase5/budget_comparison.csv"),
        Path("tables/phase5/scenario_pool_transfer.csv"),
        Path("logs/phase5/ccg_iterations.csv"),
    ):
        lines = (output_root / relative_path).read_text(
            encoding="utf-8-sig"
        ).splitlines()
        assert len(lines) == 1


def test_second_budget_state_transfer_failure_preserves_first_budget(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original = spw_ccg_module.build_transferred_state
    calls = 0

    def fail_second_transfer(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic state transfer failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(
        spw_ccg_module,
        "build_transferred_state",
        fail_second_transfer,
    )

    payload = run(Path("configs/phase5.yaml"), tmp_path)

    assert payload["status"] == "state_transfer_exception"
    assert payload["completed_budget_count"] == 1
    assert len(payload["comparisons"]) == 1
    assert payload["comparisons"][0]["budget"] == 700.0
    assert payload["failure"]["budget"] == 800.0
    assert payload["failure"]["stage"] == "state_transfer"
    assert payload["failure"]["exception_type"] == "RuntimeError"
    assert payload["failure"]["cold_result"]["converged"]
    assert payload["failure"]["warm_result"]["converged"]

    solution_path = (
        tmp_path / "solutions" / "phase5" / "spw_ccg_results.json"
    )
    written_payload = json.loads(solution_path.read_text(encoding="utf-8"))
    assert written_payload["completed_budget_count"] == 1
    assert len(written_payload["comparisons"]) == 1

    comparison_path = (
        tmp_path / "tables" / "phase5" / "budget_comparison.csv"
    )
    with comparison_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert rows[0]["status"] == "optimal"
    assert rows[1]["status"] == "state_transfer_exception"


def test_main_exits_nonzero_after_failed_run(monkeypatch) -> None:
    failed_payload = {
        "status": "runner_exception",
        "budgets": [],
        "completed_budget_count": 0,
        "total_cold_seconds": 0.0,
        "total_warm_seconds": 0.0,
        "total_iteration_reduction": 0,
        "comparisons": [],
        "failure": {
            "stage": "runner",
            "exception_type": "RuntimeError",
            "message": "synthetic runner failure",
        },
    }
    monkeypatch.setattr(
        run_phase5_module,
        "run",
        lambda config_path, output_root: failed_payload,
    )
    monkeypatch.setattr(sys, "argv", ["run_phase5"])

    with pytest.raises(SystemExit, match="phase 5 failed"):
        run_phase5_module.main()
