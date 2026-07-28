from concurrent.futures import ProcessPoolExecutor
import csv
import json
import multiprocessing
from pathlib import Path
from time import monotonic, sleep
from typing import Any

import pytest

from src import phase6_runner
from src.phase6_locking import exclusive_file_lock
from src.phase6_runner import run_phase6_sequence
from src.phase6_protocol import Phase6ProtocolError


MATRIX_PATH = Path("configs/phase6_experiment_matrix.yaml")
RUNNER_CONFIG_PATH = Path("configs/phase6_runner.yaml")


def test_runner_config_is_gurobi_only(tmp_path: Path) -> None:
    config = RUNNER_CONFIG_PATH.read_text(encoding="utf-8")
    invalid = tmp_path / "invalid_runner.yaml"
    invalid.write_text(
        config.replace("    - gurobi", "    - highs"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Gurobi-only"):
        phase6_runner.load_phase6_runner_config(invalid)


def test_gurobi_version_preflight_precedes_scenario_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    generated = False

    def reject_version() -> None:
        raise RuntimeError(
            "Gurobi Optimizer version mismatch: required 13.0.2, found 13.0.1"
        )

    def forbidden_generation(*args, **kwargs):
        nonlocal generated
        generated = True
        raise AssertionError("scenario generation must not start")

    monkeypatch.setattr(
        phase6_runner,
        "validate_gurobi_runtime",
        reject_version,
    )
    monkeypatch.setattr(
        phase6_runner,
        "generate_phase6_data",
        forbidden_generation,
    )

    with pytest.raises(RuntimeError, match="version mismatch"):
        run_phase6_sequence(
            matrix_path=MATRIX_PATH,
            runner_config_path=RUNNER_CONFIG_PATH,
            output_root=tmp_path,
            tier_id="V1",
            seed=2026072001,
            execution_mode="pilot",
            run_id="pilot_v1_wrong_gurobi_version",
            worker_executor=lambda *args, **kwargs: {},
        )

    assert generated is False


def _hold_run_lock(lock_path: str, marker_path: str) -> None:
    with exclusive_file_lock(Path(lock_path), timeout_seconds=5.0):
        Path(marker_path).write_text("locked", encoding="utf-8")
        sleep(1.0)


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
            "solver": "gurobi_direct",
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


def test_formal_projection_is_checked_before_scenario_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    generated = False

    def reject_projection(**kwargs):
        raise ValueError("pilot compute gate has not passed")

    def forbidden_generation(*args, **kwargs):
        nonlocal generated
        generated = True
        raise AssertionError("scenario generation must not start")

    monkeypatch.setattr(
        phase6_runner,
        "validate_execution_seed",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        phase6_runner,
        "validate_formal_projection",
        reject_projection,
    )
    monkeypatch.setattr(
        phase6_runner,
        "generate_phase6_data",
        forbidden_generation,
    )

    with pytest.raises(ValueError, match="compute gate"):
        run_phase6_sequence(
            matrix_path=MATRIX_PATH,
            runner_config_path=RUNNER_CONFIG_PATH,
            output_root=tmp_path,
            tier_id="V1",
            seed=2026072401,
            execution_mode="formal",
            run_id="formal_gate",
            worker_executor=lambda *args: {},
        )
    assert generated is False


def test_budget_watchdog_retains_latest_worker_progress(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeProcess:
        returncode = -9
        pid = 99999

        def __init__(self, command, **kwargs):
            request_path = Path(
                command[command.index("--request") + 1]
            )
            request = json.loads(
                request_path.read_text(encoding="utf-8")
            )
            Path(request["progress_path"]).write_text(
                json.dumps(
                    {
                        "status": "running",
                        "iteration": 3,
                        "current_scenario_set": ["s0000", "s0007"],
                        "lower_bound": 120.0,
                        "upper_bound": 125.0,
                        "worst_scenario": "s0007",
                        "iteration_log": [{"iteration": 3}],
                    }
                ),
                encoding="utf-8",
            )

        def poll(self):
            return None

        def kill(self):
            return None

        def communicate(self):
            return "", ""

    class FakeMonitored:
        def __init__(self, pid):
            self.pid = pid

        def children(self, recursive=True):
            return []

        def kill(self):
            return None

    monkeypatch.setattr(
        phase6_runner.subprocess,
        "Popen",
        FakeProcess,
    )
    monkeypatch.setattr(
        phase6_runner.psutil,
        "Process",
        FakeMonitored,
    )
    monkeypatch.setattr(
        phase6_runner.psutil,
        "wait_procs",
        lambda processes, timeout: (processes, []),
    )

    payload = phase6_runner._default_worker_executor(
        {
            "attempt": 1,
            "budget_index": 0,
            "algorithm": "cold",
            "repetition": 1,
            "tier_id": "V1",
            "seed": 2026072001,
            "budget": 1000.0,
        },
        1.0e-9,
        tmp_path,
    )

    assert payload["status"] == "budget_wall_timeout"
    assert payload["partial_progress"]["iteration"] == 3
    assert payload["partial_progress"]["lower_bound"] == 120.0
    assert payload["partial_progress"]["upper_bound"] == 125.0
    result_path = tmp_path / "a01_b00_cold_r01_result.json"
    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved["partial_progress"]["worst_scenario"] == "s0007"


def test_terminal_failure_is_immutable_and_retry_has_lineage(
    tmp_path: Path,
) -> None:
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
    assert failed["status"] == "solver_error"
    assert failed["completed_budget_count"] == 1
    assert len(failed["comparisons"]) == 6
    assert [row["status"] for row in failed["comparisons"]] == [
        "optimal",
        "solver_error",
        "not_run_after_pair_sequence_failure",
        "not_run_after_pair_sequence_failure",
        "not_run_after_pair_sequence_failure",
        "not_run_after_pair_sequence_failure",
    ]
    assert failed["comparisons"][1]["warm"]["status"] == "solver_error"
    assert failed["comparisons"][1]["cold"]["status"] == (
        "not_run_after_pair_failure"
    )
    run_directory = (
        tmp_path
        / "experiments"
        / "phase6"
        / "runs"
        / "pilot_v1_resume"
    )
    with (run_directory / "budget_comparison.csv").open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        budget_rows = list(csv.DictReader(handle))
    assert len(budget_rows) == 6
    assert budget_rows[1]["warm_status"] == "solver_error"
    assert budget_rows[2]["status"] == (
        "not_run_after_pair_sequence_failure"
    )
    with (
        tmp_path
        / "experiments"
        / "phase6"
        / "algorithm_performance.csv"
    ).open("r", encoding="utf-8-sig", newline="") as handle:
        performance_rows = [
            row
            for row in csv.DictReader(handle)
            if row["run_id"] == "pilot_v1_resume"
        ]
    assert len(performance_rows) == 6 * 2 * 3
    statuses = {row["status"] for row in performance_rows}
    assert "solver_error" in statuses
    assert "not_run_after_pair_failure" in statuses
    assert "not_run_after_pair_sequence_failure" in statuses

    def successful_executor(
        request: dict[str, Any],
        timeout_seconds: float,
        work_directory: Path,
    ) -> dict[str, Any]:
        return _fake_result(request)

    with pytest.raises(
        Phase6ProtocolError,
        match="running or interrupted",
    ):
        run_phase6_sequence(
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

    diagnostic = run_phase6_sequence(
        matrix_path=MATRIX_PATH,
        runner_config_path=RUNNER_CONFIG_PATH,
        output_root=tmp_path,
        tier_id="V1",
        seed=2026072001,
        execution_mode="pilot",
        run_id="pilot_v1_diagnostic",
        parent_run_id="pilot_v1_resume",
        worker_executor=successful_executor,
    )
    assert diagnostic["status"] == "optimal"
    assert diagnostic["parent_run_id"] == "pilot_v1_resume"

    registry_path = (
        tmp_path / "experiments" / "phase6" / "run_registry.csv"
    )
    with registry_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        rows = {row["run_id"]: row for row in csv.DictReader(handle)}
    assert rows["pilot_v1_resume"]["status"] == "solver_error"
    assert rows["pilot_v1_diagnostic"]["parent_run_id"] == (
        "pilot_v1_resume"
    )
    projection = json.loads(
        (
            tmp_path
            / "experiments"
            / "phase6"
            / "pilot_throughput_projection.json"
        ).read_text(encoding="utf-8")
    )
    assert projection["failed_primary_runs"][0]["run_id"] == (
        "pilot_v1_resume"
    )
    assert projection["diagnostic_attempts"][0]["run_id"] == (
        "pilot_v1_diagnostic"
    )


def test_interrupted_checkpoint_can_resume_from_completed_prefix(
    tmp_path: Path,
) -> None:
    def interrupted_executor(
        request: dict[str, Any],
        timeout_seconds: float,
        work_directory: Path,
    ) -> dict[str, Any]:
        if (
            int(request["budget_index"]) == 1
            and request["algorithm"] == "warm"
        ):
            raise RuntimeError("synthetic process interruption")
        return _fake_result(request)

    with pytest.raises(RuntimeError, match="process interruption"):
        run_phase6_sequence(
            matrix_path=MATRIX_PATH,
            runner_config_path=RUNNER_CONFIG_PATH,
            output_root=tmp_path,
            tier_id="V1",
            seed=2026072001,
            execution_mode="pilot",
            run_id="pilot_v1_interrupted",
            worker_executor=interrupted_executor,
        )
    checkpoint_path = (
        tmp_path
        / "experiments"
        / "phase6"
        / "runs"
        / "pilot_v1_interrupted"
        / "checkpoint.json"
    )
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["status"] == "running"
    assert len(checkpoint["comparisons"]) == 1

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
        run_id="pilot_v1_interrupted",
        resume=True,
        worker_executor=successful_executor,
    )
    assert resumed["status"] == "optimal"
    assert resumed["completed_budget_count"] == 6
    assert min(resumed_calls) == 1


def test_same_run_id_is_exclusive_across_processes(tmp_path: Path) -> None:
    run_id = "pilot_v1_locked"
    run_directory = (
        tmp_path / "experiments" / "phase6" / "runs" / run_id
    )
    lock_path = run_directory / ".run.lock"
    marker_path = tmp_path / "lock_ready.txt"
    with ProcessPoolExecutor(
        max_workers=1,
        mp_context=multiprocessing.get_context("spawn"),
    ) as executor:
        future = executor.submit(
            _hold_run_lock,
            str(lock_path),
            str(marker_path),
        )
        deadline = monotonic() + 5.0
        while not marker_path.exists() and monotonic() < deadline:
            sleep(0.02)
        assert marker_path.exists()
        with pytest.raises(TimeoutError, match="Phase 6 lock"):
            run_phase6_sequence(
                matrix_path=MATRIX_PATH,
                runner_config_path=RUNNER_CONFIG_PATH,
                output_root=tmp_path,
                tier_id="V1",
                seed=2026072001,
                execution_mode="pilot",
                run_id=run_id,
                worker_executor=lambda *args: {},
            )
        future.result(timeout=5.0)
    assert not (run_directory / "checkpoint.json").exists()
