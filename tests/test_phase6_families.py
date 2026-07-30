from __future__ import annotations

import csv
from dataclasses import replace
import json
from pathlib import Path
import shutil

import pytest

from src.evaluation import EvaluationResult
from src.phase6_families import (
    FAMILY_COMPONENT_FILES,
    FAMILY_REGISTRY_FIELDS,
    aggregate_oos_evaluation,
    enumerate_family_plans,
    family_code_sha256,
    sensitivity_configurations,
    update_family_projection,
)
from src.phase6_family_runner import (
    _validate_family_pilot_order,
    load_family_runner_config,
)
from src.phase6_protocol import generate_phase6_data, load_phase6_matrix
from src.recourse_model import RecourseResult
from src.reproducibility import sha256_file


MATRIX_PATH = Path("configs/phase6_experiment_matrix.yaml").resolve()
FAMILY_CONFIG_PATH = Path("configs/phase6_family_runner.yaml").resolve()


def test_formal_family_plan_counts_match_frozen_matrix() -> None:
    matrix = load_phase6_matrix(MATRIX_PATH)
    assert {
        family: len(
            enumerate_family_plans(
                matrix,
                family,
                matrix_path=MATRIX_PATH,
            )
        )
        for family in ("E1", "E2", "E4", "E5")
    } == {"E1": 45, "E2": 180, "E4": 90, "E5": 75}
    configurations = sensitivity_configurations(matrix)
    assert len(configurations) == 15
    assert len({row["configuration_id"] for row in configurations}) == 15
    assert sum(row["design"] == "ofat" for row in configurations) == 11
    assert sum(row["design"] == "interaction" for row in configurations) == 4


def test_every_family_code_dependency_changes_fingerprint(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    originals: dict[str, bytes] = {}
    for relative in FAMILY_COMPONENT_FILES:
        source = Path(relative)
        destination = project / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        originals[relative] = source.read_bytes()
    baseline = family_code_sha256(project)
    for relative in FAMILY_COMPONENT_FILES:
        path = project / relative
        path.write_bytes(originals[relative] + b"\n# fingerprint mutation\n")
        assert family_code_sha256(project) != baseline, relative
        path.write_bytes(originals[relative])


def _recourse(
    scenario: str,
    *,
    objective: float,
    shortage: float,
    waste: float,
    spend: float,
) -> RecourseResult:
    return RecourseResult(
        scenario=scenario,
        status="optimal",
        objective=objective,
        emergency_purchase={"relief_food_1": [spend / 2.0] * 4},
        emergency_spend=spend,
        shortage={"relief_food_1": [shortage, 0.0, 0.0, 0.0]},
        waste={"relief_food_1": [waste, 0.0, 0.0, 0.0]},
        ending_inventory={"relief_food_1": [[0.0]] * 4},
        solver="gurobi_direct",
        runtime_seconds=0.1,
        termination_condition="optimal",
    )


def test_oos_metrics_use_count_identity_and_demand_weighted_service() -> None:
    matrix = load_phase6_matrix(MATRIX_PATH)
    generated = generate_phase6_data(
        matrix,
        matrix_path=MATRIX_PATH,
        tier_id="D0",
        seed=20260723,
        budget=853.5,
    )
    data = generated.data.subset(generated.data.scenarios[:2])
    results = {
        data.scenarios[0]: _recourse(
            data.scenarios[0],
            objective=10.0,
            shortage=1.0,
            waste=2.0,
            spend=3.0,
        ),
        data.scenarios[1]: _recourse(
            data.scenarios[1],
            objective=20.0,
            shortage=0.0,
            waste=4.0,
            spend=5.0,
        ),
    }
    evaluation = EvaluationResult(
        status="optimal",
        regular_cost=100.0,
        robust_objective=120.0,
        worst_scenario=data.scenarios[1],
        worst_recourse_cost=20.0,
        scenario_results=results,
        infeasible_scenarios=(),
        failed_scenarios=(),
        runtime_seconds=0.2,
    )
    metrics = aggregate_oos_evaluation(data, evaluation, reserve=10.0)
    total_demand = sum(
        sum(data.demand[s][data.items[0]])
        for s in data.scenarios
    )
    assert metrics["total_scenario_count"] == 2
    assert metrics["optimal_scenario_count"] == 2
    assert metrics["infeasible_scenario_count"] == 0
    assert metrics["solver_failure_count"] == 0
    assert metrics["mean_total_cost"] == pytest.approx(115.0)
    assert metrics["service_level"] == pytest.approx(
        1.0 - 1.0 / total_demand
    )
    assert metrics["reserve_utilization"] == pytest.approx(0.4)
    assert metrics["zero_reserve_flag"] is False


def test_oos_infeasibility_never_receives_big_m_aggregate() -> None:
    matrix = load_phase6_matrix(MATRIX_PATH)
    generated = generate_phase6_data(
        matrix,
        matrix_path=MATRIX_PATH,
        tier_id="D0",
        seed=20260723,
        budget=853.5,
    )
    data = generated.data.subset(generated.data.scenarios[:2])
    optimal = _recourse(
        data.scenarios[0],
        objective=10.0,
        shortage=0.0,
        waste=0.0,
        spend=0.0,
    )
    infeasible = replace(
        optimal,
        scenario=data.scenarios[1],
        status="infeasible",
        objective=None,
        emergency_spend=None,
    )
    evaluation = EvaluationResult(
        status="infeasible_recourse",
        regular_cost=100.0,
        robust_objective=None,
        worst_scenario=None,
        worst_recourse_cost=None,
        scenario_results={
            data.scenarios[0]: optimal,
            data.scenarios[1]: infeasible,
        },
        infeasible_scenarios=(data.scenarios[1],),
        failed_scenarios=(),
        runtime_seconds=0.2,
    )
    metrics = aggregate_oos_evaluation(data, evaluation, reserve=0.0)
    assert metrics["plan_oos_status"] == "contains_infeasible_recourse"
    assert metrics["optimal_scenario_count"] == 1
    assert metrics["infeasible_scenario_count"] == 1
    assert metrics["mean_total_cost"] is None
    assert metrics["total_cost_cvar95"] is None
    assert metrics["zero_reserve_flag"] is True


def test_projection_filters_family_runner_configuration_hash(
    tmp_path: Path,
) -> None:
    matrix = load_phase6_matrix(MATRIX_PATH)
    base = tmp_path / "experiments" / "phase6"
    base.mkdir(parents=True)
    (base / "pilot_throughput_projection.json").write_text(
        json.dumps(
            {
                "scientific_config_sha256": "science",
                "completed_run_count": 12,
                "required_run_count": 12,
                "missing_runs": [],
                "failed_primary_runs": [],
                "duplicate_primary_runs": [],
                "family_projection": {
                    "E1": {"status": "unavailable"},
                    "E2": {"status": "unavailable"},
                    "E3": {
                        "status": "projected",
                        "projected_wall_hours": 1.0,
                    },
                    "E4": {"status": "unavailable"},
                    "E5": {"status": "unavailable"},
                },
            }
        ),
        encoding="utf-8",
    )
    rows = [
        (
            "run_id,parent_run_id,family,execution_mode,tier_id,seed,status,"
            "planned_work_units,completed_work_units,wall_seconds,"
            "peak_memory_mb,scientific_config_sha256,"
            "family_config_sha256,family_code_sha256,"
            "environment_sha256,started_at_utc,updated_at_utc,"
            "failure_stage,failure_message,result_path"
            ",manifest_path"
        )
    ]
    for family in ("E1", "E2", "E4", "E5"):
        for seed in (2026072001, 2026072002, 2026072003):
            run_id = f"{family}_{seed}"
            run_directory = base / "family_runs" / run_id
            run_directory.mkdir(parents=True)
            result_path = run_directory / "result.json"
            manifest_path = run_directory / "manifest.json"
            result_path.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "family": family,
                        "execution_mode": "pilot",
                        "tier_ids": ["V1"],
                        "seed": seed,
                        "parent_run_id": None,
                        "status": "optimal",
                        "finalized": True,
                        "planned_work_units": 1,
                        "completed_work_units": 1,
                        "wall_seconds": 3600.0,
                        "fingerprints": {
                            "scientific_config_sha256": "science",
                            "family_config_sha256": "config",
                            "family_code_sha256": "code",
                            "environment_sha256": "environment",
                        },
                    }
                ),
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps(
                    {
                        "artifact_state": "finalized",
                        "run_id": run_id,
                        "family": family,
                        "result_path": str(result_path.resolve()),
                        "result_sha256": sha256_file(result_path),
                        "scientific_config_sha256": "science",
                        "family_config_sha256": "config",
                        "family_code_sha256": "code",
                        "environment_sha256": "environment",
                    }
                ),
                encoding="utf-8",
            )
            rows.append(
                f"{run_id},,{family},pilot,V1,{seed},optimal,"
                "1,1,3600,1,science,config,code,environment,,,,,"
                f"{result_path.resolve()},{manifest_path.resolve()}"
            )
    rows.append(
        "stale,,E1,pilot,V1,2026072001,optimal,1,1,1,1,"
        "science,stale-config,code,environment,,,,,,"
    )
    (base / "family_run_registry.csv").write_text(
        "\n".join(rows) + "\n",
        encoding="utf-8-sig",
    )
    projection = update_family_projection(
        output_root=tmp_path,
        matrix=matrix,
        scientific_config_hash="science",
        family_config_hash="config",
        family_code_hash="code",
        environment_hash="environment",
    )
    assert projection["family_projection"]["E1"]["pilot_run_ids"] == [
        "E1_2026072001",
        "E1_2026072002",
        "E1_2026072003",
    ]
    assert projection["family_config_sha256"] == "config"


def test_projection_rejects_tampered_result_bytes(tmp_path: Path) -> None:
    matrix = load_phase6_matrix(MATRIX_PATH)
    base = tmp_path / "experiments" / "phase6"
    base.mkdir(parents=True)
    (base / "pilot_throughput_projection.json").write_text(
        json.dumps(
            {
                "completed_run_count": 12,
                "required_run_count": 12,
                "missing_runs": [],
                "failed_primary_runs": [],
                "duplicate_primary_runs": [],
                "family_projection": {
                    family: (
                        {"status": "projected", "projected_wall_hours": 1.0}
                        if family == "E3"
                        else {"status": "unavailable"}
                    )
                    for family in ("E1", "E2", "E3", "E4", "E5")
                },
            }
        ),
        encoding="utf-8",
    )
    header = (
        "run_id,parent_run_id,family,execution_mode,tier_id,seed,status,"
        "planned_work_units,completed_work_units,wall_seconds,peak_memory_mb,"
        "scientific_config_sha256,family_config_sha256,family_code_sha256,"
        "environment_sha256,started_at_utc,updated_at_utc,failure_stage,"
        "failure_message,result_path,manifest_path"
    )
    rows = [header]
    tampered_run = "E1_2026072001"
    for family in ("E1", "E2", "E4", "E5"):
        for seed in (2026072001, 2026072002, 2026072003):
            run_id = f"{family}_{seed}"
            directory = base / "family_runs" / run_id
            directory.mkdir(parents=True)
            result_path = directory / "result.json"
            manifest_path = directory / "manifest.json"
            result = {
                "run_id": run_id,
                "family": family,
                "execution_mode": "pilot",
                "tier_ids": ["V1"],
                "seed": seed,
                "parent_run_id": None,
                "status": "optimal",
                "finalized": True,
                "planned_work_units": 1,
                "completed_work_units": 1,
                "wall_seconds": 3600.0,
                "fingerprints": {
                    "scientific_config_sha256": "science",
                    "family_config_sha256": "config",
                    "family_code_sha256": "code",
                    "environment_sha256": "environment",
                },
            }
            result_path.write_text(json.dumps(result), encoding="utf-8")
            manifest = {
                "artifact_state": "finalized",
                "run_id": run_id,
                "family": family,
                "result_path": str(result_path.resolve()),
                "result_sha256": sha256_file(result_path),
                **result["fingerprints"],
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            if run_id == tampered_run:
                result_path.write_text(
                    json.dumps({**result, "tampered": True}),
                    encoding="utf-8",
                )
            rows.append(
                f"{run_id},,{family},pilot,V1,{seed},optimal,1,1,3600,1,"
                "science,config,code,environment,,,,,"
                f"{result_path.resolve()},{manifest_path.resolve()}"
            )
    (base / "family_run_registry.csv").write_text(
        "\n".join(rows) + "\n",
        encoding="utf-8-sig",
    )
    projection = update_family_projection(
        output_root=tmp_path,
        matrix=matrix,
        scientific_config_hash="science",
        family_config_hash="config",
        family_code_hash="code",
        environment_hash="environment",
    )
    e1 = projection["family_projection"]["E1"]
    assert e1["status"] == "family_pilot_failure"
    assert tampered_run in e1["artifact_errors"]


@pytest.mark.parametrize(
    ("field", "tampered_value"),
    (
        ("execution_mode", "formal"),
        ("seed", "2026072999"),
        ("parent_run_id", "diagnostic_parent"),
        ("wall_seconds", "7200.0"),
        ("tier_id", "V2"),
    ),
)
def test_registry_field_tampering_blocks_order_and_projection(
    tmp_path: Path,
    field: str,
    tampered_value: str,
) -> None:
    matrix = load_phase6_matrix(MATRIX_PATH)
    config = load_family_runner_config(FAMILY_CONFIG_PATH)
    base = tmp_path / "experiments" / "phase6"
    base.mkdir(parents=True)
    (base / "pilot_throughput_projection.json").write_text(
        json.dumps(
            {
                "completed_run_count": 12,
                "required_run_count": 12,
                "missing_runs": [],
                "failed_primary_runs": [],
                "duplicate_primary_runs": [],
                "family_projection": {
                    family: (
                        {
                            "status": "projected",
                            "projected_wall_hours": 1.0,
                        }
                        if family == "E3"
                        else {"status": "unavailable"}
                    )
                    for family in ("E1", "E2", "E3", "E4", "E5")
                },
            }
        ),
        encoding="utf-8",
    )
    registry_rows: list[dict[str, object]] = []
    target_run_id = "E1_2026072001"
    fingerprints = {
        "scientific_config_sha256": "science",
        "family_config_sha256": "config",
        "family_code_sha256": "code",
        "environment_sha256": "environment",
    }
    for family in ("E1", "E2", "E4", "E5"):
        for seed in (2026072001, 2026072002, 2026072003):
            run_id = f"{family}_{seed}"
            directory = base / "family_runs" / run_id
            directory.mkdir(parents=True)
            result_path = directory / "result.json"
            manifest_path = directory / "manifest.json"
            result = {
                "run_id": run_id,
                "parent_run_id": None,
                "family": family,
                "execution_mode": "pilot",
                "tier_ids": ["V1"],
                "seed": seed,
                "status": "optimal",
                "finalized": True,
                "planned_work_units": 1,
                "completed_work_units": 1,
                "wall_seconds": 3600.0,
                "fingerprints": fingerprints,
            }
            result_path.write_text(json.dumps(result), encoding="utf-8")
            manifest_path.write_text(
                json.dumps(
                    {
                        "artifact_state": "finalized",
                        "run_id": run_id,
                        "family": family,
                        "result_path": str(result_path.resolve()),
                        "result_sha256": sha256_file(result_path),
                        **fingerprints,
                    }
                ),
                encoding="utf-8",
            )
            row: dict[str, object] = {
                "run_id": run_id,
                "parent_run_id": "",
                "family": family,
                "execution_mode": "pilot",
                "tier_id": "V1",
                "seed": seed,
                "status": "optimal",
                "planned_work_units": 1,
                "completed_work_units": 1,
                "wall_seconds": 3600.0,
                "peak_memory_mb": 1.0,
                **fingerprints,
                "started_at_utc": "",
                "updated_at_utc": "",
                "failure_stage": "",
                "failure_message": "",
                "result_path": str(result_path.resolve()),
                "manifest_path": str(manifest_path.resolve()),
            }
            if run_id == target_run_id:
                row[field] = tampered_value
            registry_rows.append(row)
    registry_path = base / "family_run_registry.csv"
    with registry_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=FAMILY_REGISTRY_FIELDS,
        )
        writer.writeheader()
        writer.writerows(registry_rows)

    with pytest.raises(ValueError, match="requires prior optimal families"):
        _validate_family_pilot_order(
            output_root=tmp_path,
            config=config,
            family="E2",
            seed=2026072001,
            scientific_hash="science",
            family_config_hash="config",
            family_code_hash="code",
            environment_hash="environment",
        )

    projection = update_family_projection(
        output_root=tmp_path,
        matrix=matrix,
        scientific_config_hash="science",
        family_config_hash="config",
        family_code_hash="code",
        environment_hash="environment",
    )
    e1 = projection["family_projection"]["E1"]
    assert e1["status"] == "family_pilot_failure"
    assert target_run_id in e1["artifact_errors"]
    assert projection["formal_execution_authorized"] is False
