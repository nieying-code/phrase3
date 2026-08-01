import json
from pathlib import Path
from types import SimpleNamespace

from src import phase6_io, phase6_worker
from src.phase6_worker import execute_worker_request


def test_atomic_write_retries_transient_windows_permission_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "progress.json"
    real_replace = phase6_io.os.replace
    calls = 0

    def transient_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise PermissionError(5, "transient Windows file lock")
        real_replace(source, destination)

    monkeypatch.setattr(phase6_io.os, "replace", transient_replace)
    monkeypatch.setattr(phase6_io, "sleep", lambda _: None)

    phase6_worker._atomic_write_json(target, {"status": "running"})

    assert calls == 3
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "status": "running"
    }
    assert not list(tmp_path.glob("*.tmp-*"))


def test_phase6_worker_writes_iteration_heartbeat(
    tmp_path: Path,
    monkeypatch,
) -> None:
    iteration = SimpleNamespace(
        as_dict=lambda: {
            "iteration": 1,
            "LB": 100.0,
            "global_UB": 100.0,
        }
    )
    result_payload = {
        "termination_status": "optimal",
        "converged": True,
        "iterations": 1,
        "final_scenario_set": ["s0000"],
    }

    def fake_ccg(data, **kwargs):
        kwargs["progress_callback"](
            {
                "status": "running",
                "iteration": 1,
                "termination_status": "optimal",
                "converged": True,
                "initial_scenario_set": ["s0000"],
                "current_scenario_set": ["s0000"],
                "lower_bound": 100.0,
                "upper_bound": 100.0,
                "gap": 0.0,
                "worst_scenario": "s0000",
                "iteration_log": [iteration.as_dict()],
            }
        )
        return SimpleNamespace(
            converged=True,
            termination_status="optimal",
            iterations=1,
            initial_scenario_set=("s0000",),
            final_scenario_set=("s0000",),
            lower_bound=100.0,
            upper_bound=100.0,
            gap=0.0,
            worst_scenario="s0000",
            iteration_log=(iteration,),
            as_dict=lambda: result_payload,
        )

    monkeypatch.setattr(phase6_worker, "run_standard_ccg", fake_ccg)
    progress_path = tmp_path / "progress.json"
    result = execute_worker_request(
        {
            "matrix_path": str(
                Path("configs/phase6_experiment_matrix.yaml").resolve()
            ),
            "tier_id": "D0",
            "seed": 20260723,
            "budget": 1000.0,
            "algorithm": "cold",
            "previous_state": None,
            "progress_path": str(progress_path),
            "solver": {
                "preference": ["gurobi"],
                "call_time_limit_seconds": 60.0,
                "threads": 1,
                "feasibility_tolerance": 1.0e-7,
                "optimality_tolerance": 1.0e-7,
                "tee": False,
            },
            "ccg": {
                "absolute_tolerance": 1.0e-6,
                "relative_tolerance": 1.0e-6,
                "max_iterations": 200,
            },
        }
    )

    assert result["status"] == "optimal"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress["status"] == "completed"
    assert progress["iteration"] == result["ccg_result"]["iterations"]
    assert progress["iteration_log"]
    assert progress["current_scenario_set"] == result["ccg_result"][
        "final_scenario_set"
    ]
