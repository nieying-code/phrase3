from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.run_phase4 import run


def test_formal_phase4_run_writes_complete_outputs(tmp_path: Path) -> None:
    payload = run(Path("configs/phase4.yaml"), tmp_path)

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
        tmp_path / "solutions" / "phase4" / "spw_ccg_results.json"
    )
    comparison_path = (
        tmp_path / "tables" / "phase4" / "budget_comparison.csv"
    )
    transfer_path = (
        tmp_path / "tables" / "phase4" / "scenario_pool_transfer.csv"
    )
    iteration_path = (
        tmp_path / "logs" / "phase4" / "ccg_iterations.csv"
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
