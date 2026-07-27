from pathlib import Path
from typing import Any

from src.phase6_runner import run_phase6_sequence


MATRIX_PATH = Path("configs/phase6_experiment_matrix.yaml")
RUNNER_CONFIG_PATH = Path("configs/phase6_runner.yaml")


def _fake_result(request: dict[str, Any], *, status: str = "optimal") -> dict[str, Any]:
    budget = float(request["budget"])
    mode = str(request["algorithm"])
    repetition = int(request["repetition"])
    if status != "optimal":
        return {
            "status": status,
            "algorithm": mode,
            "budget": budget,
            "ccg_result": None,
            "failure": {
                "stage": mode,
                "exception_type": "SyntheticFailure",
                "message": "synthetic worker failure",
            },
            "subprocess_wall_seconds": 0.1,
            "peak_memory_mb": 10.0,
        }
    objective = 5000.0 - budget
    return {
        "status": "optimal",
        "algorithm": mode,
        "tier_id": request["tier_id"],
        "seed": request["seed"],
        "budget": budget,
        "budget_factor": None,
        "reference_budget": None,
        "generator_protocol_id": "phase6_controlled_synthetic_v1_0",
        "scenario_count": 2,
        "initial_scenarios": ["s0000"],
        "pool_build_seconds": 0.01,
        "worker_wall_seconds": 0.1,
        "subprocess_wall_seconds": 0.1 + 0.01 * repetition,
        "peak_memory_mb": 10.0 + repetition,
        "return_code": 0,
        "stdout": "",
        "stderr": "",
        "failure": None,
        "ccg_result": {
            "termination_status": "optimal",
            "converged": True,
            "objective": objective,
            "lower_bound": objective,
            "upper_bound": objective,
            "gap": 0.0,
            "iterations": 1,
            "initial_scenario_set": ["s0000"],
            "final_scenario_set": ["s0000", "s0001"],
            "regular_purchase": {"relief_food_1": [0.0] * 6},
            "reserve": budget,
            "reserve_ratio": 1.0,
            "worst_scenario": "s0001",
            "exact_scenario_costs": {
                "s0000": objective - 1.0,
                "s0001": objective,
            },
            "total_runtime_seconds": 0.1,
            "master_runtime_seconds": 0.04,
            "oracle_runtime_seconds": 0.06,
            "solver": "appsi_highs",
            "iteration_log": [
                {
                    "iteration": 1,
                    "scenario_count": 1,
                    "added_scenario": "s0001",
                    "added_type": "worst_cost",
                    "LB": objective,
                    "candidate_UB": objective,
                    "global_UB": objective,
                    "gap": 0.0,
                    "regular_cost": 0.0,
                    "R": budget,
                    "R/B": 1.0,
                    "master_time": 0.04,
                    "oracle_time": 0.06,
                    "infeasible_scenario_count": 0,
                    "worst_recourse_cost": objective,
                    "worst_scenario": "s0001",
                }
            ],
            "incumbent_evaluation": None,
        },
    }


def test_phase6_runner_checkpoints_every_pair_and_alternates_order(
    tmp_path: Path,
) -> None:
    calls: list[tuple[int, str, int]] = []

    def executor(
        request: dict[str, Any],
        timeout_seconds: float,
        work_directory: Path,
    ) -> dict[str, Any]:
        assert timeout_seconds > 0.0
        calls.append(
            (
                int(request["budget_index"]),
                str(request["algorithm"]),
                int(request["repetition"]),
            )
        )
        return _fake_result(request)

    result = run_phase6_sequence(
        matrix_path=MATRIX_PATH,
        runner_config_path=RUNNER_CONFIG_PATH,
        output_root=tmp_path,
        tier_id="V1",
        seed=2026072001,
        execution_mode="pilot",
        run_id="pilot_v1_test",
        worker_executor=executor,
    )

    assert result["status"] == "optimal"
    assert result["completed_budget_count"] == 6
    assert len(calls) == 6 * 2 * 3
    assert result["comparisons"][0]["execution_order"] == ["cold", "warm"]
    assert result["comparisons"][1]["execution_order"] == ["warm", "cold"]
    checkpoint = (
        tmp_path
        / "experiments"
        / "phase6"
        / "runs"
        / "pilot_v1_test"
        / "checkpoint.json"
    )
    assert checkpoint.exists()
    assert (
        tmp_path / "experiments" / "phase6" / "run_registry.csv"
    ).exists()
    assert (
        tmp_path
        / "experiments"
        / "phase6"
        / "algorithm_performance.csv"
    ).exists()
    assert result["reporting"]["pilot_projection_status"] == (
        "insufficient_pilot_coverage"
    )
    assert result["reporting"]["formal_execution_authorized"] is False


def test_phase6_runner_resumes_from_last_completed_budget(tmp_path: Path) -> None:
    first_calls: list[int] = []

    def failing_executor(
        request: dict[str, Any],
        timeout_seconds: float,
        work_directory: Path,
    ) -> dict[str, Any]:
        first_calls.append(int(request["budget_index"]))
        if (
            int(request["budget_index"]) == 1
            and request["algorithm"] == "warm"
        ):
            return _fake_result(request, status="solver_error")
        return _fake_result(request)

    failed = run_phase6_sequence(
        matrix_path=MATRIX_PATH,
        runner_config_path=RUNNER_CONFIG_PATH,
        output_root=tmp_path,
        tier_id="V1",
        seed=2026072001,
        execution_mode="pilot",
        run_id="pilot_v1_resume",
        worker_executor=failing_executor,
    )
    assert failed["status"] == "algorithm_failure"
    assert failed["completed_budget_count"] == 1

    resumed_calls: list[int] = []

    def successful_executor(
        request: dict[str, Any],
        timeout_seconds: float,
        work_directory: Path,
    ) -> dict[str, Any]:
        resumed_calls.append(int(request["budget_index"]))
        return _fake_result(request)

    resumed = run_phase6_sequence(
        matrix_path=MATRIX_PATH,
        runner_config_path=RUNNER_CONFIG_PATH,
        output_root=tmp_path,
        tier_id="V1",
        seed=2026072001,
        execution_mode="pilot",
        run_id="pilot_v1_resume",
        resume=True,
        worker_executor=successful_executor,
    )
    assert resumed["status"] == "optimal"
    assert resumed["completed_budget_count"] == 6
    assert min(resumed_calls) == 1
    assert [row["budget_index"] for row in resumed["comparisons"]] == list(
        range(6)
    )
