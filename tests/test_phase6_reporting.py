from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import csv
import json
import multiprocessing
from pathlib import Path
import shutil

import pytest

from src.phase6_protocol import load_phase6_matrix
from src.phase6_reporting import (
    update_pilot_projection,
    validate_formal_projection,
)
from src.phase6_runner import (
    PHASE6_E3_COMPONENT_FILES,
    PHASE6_E3_REQUIREMENTS_FILE,
    REGISTRY_FIELDS,
    _e3_component_code_sha256,
    _scientific_config_sha256,
    _upsert_registry,
    load_phase6_runner_config,
)
from src.reproducibility import sha256_file


MATRIX_PATH = Path("configs/phase6_experiment_matrix.yaml").resolve()
RUNNER_CONFIG_PATH = Path("configs/phase6_runner.yaml").resolve()


def _registry_row(
    *,
    run_id: str,
    tier_id: str,
    seed: int,
    result_path: Path,
    matrix_sha256: str,
    scientific_config_sha256: str,
    runner_config_sha256: str,
    e3_component_sha256: str,
    status: str = "optimal",
    parent_run_id: str | None = None,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "status": status,
        "execution_mode": "pilot",
        "tier_id": tier_id,
        "seed": seed,
        "matrix_id": "phase6_formal_experiments_v1_3",
        "matrix_sha256": matrix_sha256,
        "scientific_config_sha256": scientific_config_sha256,
        "runner_config_sha256": runner_config_sha256,
        "e3_component_sha256": e3_component_sha256,
        "planned_budget_count": 6,
        "completed_budget_count": 6 if status == "optimal" else 1,
        "started_at_utc": "2026-07-27T00:00:00+00:00",
        "updated_at_utc": "2026-07-27T00:01:00+00:00",
        "failure_stage": None if status == "optimal" else "warm",
        "failure_message": None if status == "optimal" else "failed",
        "result_path": str(result_path),
        "checkpoint_path": str(result_path.parent / "checkpoint.json"),
    }


def _write_fake_result(
    path: Path,
    *,
    run_id: str,
    tier_id: str,
    seed: int,
) -> None:
    repetitions = [
        {
            "status": "optimal",
            "subprocess_wall_seconds": 1.0,
            "peak_memory_mb": 20.0,
            "scenario_count": 50,
            "ccg_result": {"iterations": 2},
        }
    ]
    comparisons = [
        {
            "cold": {"repetitions": repetitions},
            "warm": {"repetitions": repetitions},
        }
        for _ in range(6)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "execution_mode": "pilot",
                "tier_id": tier_id,
                "seed": seed,
                "comparisons": comparisons,
            }
        ),
        encoding="utf-8",
    )


def _write_registry_process(arguments: tuple[str, int]) -> None:
    path_text, index = arguments
    row = {name: "" for name in REGISTRY_FIELDS}
    row.update(
        {
            "run_id": f"run_{index:03d}",
            "status": "running",
            "seed": index,
        }
    )
    _upsert_registry(Path(path_text), row)


def test_projection_is_fingerprinted_and_incomplete_without_family_runners(
    tmp_path: Path,
) -> None:
    matrix = load_phase6_matrix(MATRIX_PATH)
    runner_config = load_phase6_runner_config(RUNNER_CONFIG_PATH)
    matrix_hash = sha256_file(MATRIX_PATH)
    scientific_hash = _scientific_config_sha256(matrix)
    config_hash = sha256_file(RUNNER_CONFIG_PATH)
    code_hash = _e3_component_code_sha256(MATRIX_PATH.parent.parent)
    registry_path = (
        tmp_path / "experiments" / "phase6" / "run_registry.csv"
    )
    for tier in ("V1", "V2", "P1", "P2"):
        for seed in (2026072001, 2026072002, 2026072003):
            run_id = f"pilot_{tier}_{seed}"
            result_path = (
                tmp_path
                / "experiments"
                / "phase6"
                / "runs"
                / run_id
                / "result.json"
            )
            _write_fake_result(
                result_path,
                run_id=run_id,
                tier_id=tier,
                seed=seed,
            )
            _upsert_registry(
                registry_path,
                _registry_row(
                    run_id=run_id,
                    tier_id=tier,
                    seed=seed,
                    result_path=result_path,
                    matrix_sha256=matrix_hash,
                    scientific_config_sha256=scientific_hash,
                    runner_config_sha256=config_hash,
                    e3_component_sha256=code_hash,
                ),
            )
    _upsert_registry(
        registry_path,
        _registry_row(
            run_id="stale_matrix_failure",
            tier_id="V1",
            seed=2026072001,
            result_path=tmp_path / "unused.json",
            matrix_sha256="stale-matrix",
            scientific_config_sha256="stale-scientific",
            runner_config_sha256=config_hash,
            e3_component_sha256=code_hash,
            status="algorithm_failure",
        ),
    )

    projection = update_pilot_projection(
        output_root=tmp_path,
        matrix=matrix,
        runner_config=runner_config,
        matrix_sha256=matrix_hash,
        scientific_config_sha256=scientific_hash,
        runner_config_sha256=config_hash,
        e3_component_sha256=code_hash,
    )

    assert projection["completed_run_count"] == 12
    assert projection["missing_runs"] == []
    assert projection["failed_primary_runs"] == []
    assert projection["duplicate_primary_runs"] == []
    assert projection["status"] == "projection_incomplete"
    assert projection["compute_gate_passed"] is False
    assert projection["formal_execution_authorized"] is False
    assert projection["family_projection"]["E3"]["status"] == "projected"
    assert projection["family_projection"]["E1"]["status"] == "unavailable"
    assert "projected_total_wall_hours" not in projection


def test_formal_projection_gate_rejects_stale_or_unapproved_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "projection.json"
    payload = {
        "matrix_id": "matrix",
        "matrix_status": "frozen_for_formal_execution",
        "matrix_sha256": "matrix-hash",
        "scientific_config_sha256": "scientific-hash",
        "runner_config_sha256": "config-hash",
        "e3_component_sha256": "code-hash",
        "required_run_count": 12,
        "completed_run_count": 12,
        "missing_runs": [],
        "failed_primary_runs": [],
        "duplicate_primary_runs": [],
        "status": "projection_incomplete",
        "compute_gate_passed": False,
        "formal_execution_authorized": False,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="status is not passed"):
        validate_formal_projection(
            projection_path=path,
            matrix_id="matrix",
            scientific_config_sha256="scientific-hash",
            runner_config_sha256="config-hash",
            e3_component_sha256="code-hash",
        )
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        validate_formal_projection(
            projection_path=path,
            matrix_id="matrix",
            scientific_config_sha256="stale",
            runner_config_sha256="config-hash",
            e3_component_sha256="code-hash",
        )

    payload.update(
        {
            "status": "passed",
            "compute_gate_passed": True,
            "formal_execution_authorized": True,
        }
    )
    path.write_text(json.dumps(payload), encoding="utf-8")
    accepted = validate_formal_projection(
        projection_path=path,
        matrix_id="matrix",
        scientific_config_sha256="scientific-hash",
        runner_config_sha256="config-hash",
        e3_component_sha256="code-hash",
    )
    assert accepted["formal_execution_authorized"] is True


def test_registry_upserts_are_serialized_across_concurrent_writers(
    tmp_path: Path,
) -> None:
    path = tmp_path / "experiments" / "phase6" / "run_registry.csv"

    with ProcessPoolExecutor(
        max_workers=4,
        mp_context=multiprocessing.get_context("spawn"),
    ) as executor:
        list(
            executor.map(
                _write_registry_process,
                [(str(path), index) for index in range(40)],
            )
        )

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 40
    assert {row["run_id"] for row in rows} == {
        f"run_{index:03d}" for index in range(40)
    }


def test_registry_schema_migrates_legacy_fingerprint_columns(
    tmp_path: Path,
) -> None:
    path = tmp_path / "experiments" / "phase6" / "run_registry.csv"
    path.parent.mkdir(parents=True)
    legacy_fields = tuple(
        "runner_code_sha256"
        if name == "e3_component_sha256"
        else name
        for name in REGISTRY_FIELDS
        if name != "scientific_config_sha256"
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=legacy_fields)
        writer.writeheader()
        writer.writerow(
            {
                **{name: "" for name in legacy_fields},
                "run_id": "legacy",
                "runner_code_sha256": "legacy-code",
            }
        )
    row = {name: "" for name in REGISTRY_FIELDS}
    row.update({"run_id": "new", "e3_component_sha256": "current"})
    _upsert_registry(path, row)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        assert tuple(reader.fieldnames or ()) == REGISTRY_FIELDS
    assert {item["run_id"] for item in rows} == {"legacy", "new"}
    assert rows[0]["scientific_config_sha256"] == ""


def test_scientific_hash_excludes_lifecycle_but_includes_parameters() -> None:
    matrix = load_phase6_matrix(MATRIX_PATH)
    baseline = _scientific_config_sha256(matrix)
    lifecycle_only = deepcopy(matrix)
    lifecycle_only["status"] = "frozen_for_formal_execution"
    lifecycle_only["revised_on"] = "2099-01-01"
    assert _scientific_config_sha256(lifecycle_only) == baseline

    scientific_change = deepcopy(matrix)
    scientific_change["algorithm_comparison"]["max_iterations"] += 1
    assert _scientific_config_sha256(scientific_change) != baseline


def test_e3_component_hash_scope_is_explicit(tmp_path: Path) -> None:
    project_root = MATRIX_PATH.parent.parent
    assert "src/phase6_runner.py" in PHASE6_E3_COMPONENT_FILES
    assert "src/phase6_worker.py" in PHASE6_E3_COMPONENT_FILES
    assert "src/ccg.py" in PHASE6_E3_COMPONENT_FILES
    assert "src/phase6_reporting.py" not in PHASE6_E3_COMPONENT_FILES
    assert "src/run_phase6.py" not in PHASE6_E3_COMPONENT_FILES
    assert PHASE6_E3_REQUIREMENTS_FILE == "requirements-gurobi-lock.txt"
    baseline = _e3_component_code_sha256(project_root)
    assert len(baseline) == 64

    copied_root = tmp_path / "project"
    for relative in (
        *PHASE6_E3_COMPONENT_FILES,
        PHASE6_E3_REQUIREMENTS_FILE,
    ):
        source = project_root / relative
        destination = copied_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    with (copied_root / PHASE6_E3_REQUIREMENTS_FILE).open(
        "a",
        encoding="utf-8",
    ) as handle:
        handle.write("\nplotly>=6.0\n")
    assert _e3_component_code_sha256(copied_root) == baseline

    with (copied_root / "src" / "ccg.py").open(
        "a",
        encoding="utf-8",
    ) as handle:
        handle.write("\n# scientific change\n")
    assert _e3_component_code_sha256(copied_root) != baseline
