from __future__ import annotations

import json
from pathlib import Path

from src.phase6_status import MAX_SUMMARY_BYTES, render_summary, summarize_run


def test_phase6_status_is_bounded_and_omits_large_solver_payload(
    tmp_path: Path,
) -> None:
    run_id = "pilot_gurobi_v1_2026072001"
    run_directory = (
        tmp_path / "experiments" / "phase6" / "runs" / run_id
    )
    run_directory.mkdir(parents=True)
    result = {
        "run_id": run_id,
        "status": "optimal",
        "tier_id": "V1",
        "seed": 2026072001,
        "planned_budget_count": 1,
        "completed_budget_count": 1,
        "failure": None,
        "comparisons": [
            {
                "status": "optimal",
                "objective_difference": 1.0e-9,
                "planned_repetitions": 1,
                "cold": {
                    "repetitions": [
                        {
                            "status": "optimal",
                            "ccg_result": {
                                "solver": "gurobi_direct",
                                "exact_scenario_costs": {
                                    f"s{index}": float(index)
                                    for index in range(100_000)
                                },
                            },
                        }
                    ]
                },
                "warm": {
                    "repetitions": [
                        {
                            "status": "optimal",
                            "ccg_result": {"solver": "gurobi_direct"},
                        }
                    ]
                },
            }
        ],
    }
    (run_directory / "result.json").write_text(
        json.dumps(result),
        encoding="utf-8",
    )
    manifest = {
        "python": {"version": "3.12.10", "executable": "project-python"},
        "packages": {"gurobipy": "13.0.2"},
        "solver": {
            "selected": "gurobi_direct",
            "version": "13.0.2.0",
            "threads": 1,
        },
    }
    (run_directory / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    summary = summarize_run(
        tmp_path,
        run_id,
        inspect_processes=False,
    )
    rendered = render_summary(summary)

    assert len(rendered.encode("utf-8")) < MAX_SUMMARY_BYTES
    assert "exact_scenario_costs" not in rendered
    assert summary["status"] == "optimal"
    assert summary["metrics"]["comparison_count"] == 1
    assert summary["metrics"]["planned_performance_rows"] == 2
    assert summary["metrics"]["solvers"] == ["gurobi_direct"]
    assert summary["runtime"]["gurobipy"] == "13.0.2"


def test_phase6_status_reads_incomplete_checkpoint(tmp_path: Path) -> None:
    run_id = "pilot_gurobi_p1_2026072001"
    run_directory = (
        tmp_path / "experiments" / "phase6" / "runs" / run_id
    )
    run_directory.mkdir(parents=True)
    checkpoint = {
        "run_id": run_id,
        "status": "running",
        "tier_id": "P1",
        "seed": 2026072001,
        "planned_budget_count": 3,
        "completed_budget_count": 2,
        "comparisons": [],
    }
    (run_directory / "checkpoint.json").write_text(
        json.dumps(checkpoint),
        encoding="utf-8",
    )

    summary = summarize_run(
        tmp_path,
        run_id,
        inspect_processes=False,
    )

    assert summary["source"] == "checkpoint"
    assert summary["status"] == "running"
    assert summary["completed_budget_count"] == 2
