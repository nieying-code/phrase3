from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "docs/handoffs/2026-08-23_phase6_m2_1_formal_test_results_v1_0_audit.json"
CSV_PATH = ROOT / "docs/handoffs/2026-08-23_phase6_m2_1_formal_test_results_v1_0.csv"
SHA256 = __import__("re").compile(r"[0-9a-f]{64}")
STRATEGIES = (
    "M2_minimum_endpoint",
    "M2_1_validation_selected_endpoint",
    "zero_autonomous_reserve",
    "fixed_autonomous_reserve_0_10",
    "fixed_autonomous_reserve_0_30",
    "fixed_autonomous_reserve_0_50",
)
IDENTITY_FIELDS = (
    "scenario_set_sha256",
    "scenario_order_sha256",
    "latent_draw_sha256",
    "demand_sha256",
    "emergency_price_sha256",
    "emergency_supply_sha256",
    "fulfillment_sha256",
)


def _load() -> dict:
    return json.loads(AUDIT_PATH.read_text(encoding="utf-8"))


def _canonical_sha(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and values[order[end]] == values[order[cursor]]:
            end += 1
        rank = (cursor + 1 + end) / 2.0
        for index in order[cursor:end]:
            result[index] = rank
        cursor = end
    return result


def _wilcoxon_pratt(values: list[float]) -> dict[str, float]:
    ranks = _ranks([abs(value) for value in values])
    positive = sum(rank for rank, value in zip(ranks, values, strict=True) if value > 0)
    negative = sum(rank for rank, value in zip(ranks, values, strict=True) if value < 0)
    nonzero = [rank for rank, value in zip(ranks, values, strict=True) if value != 0]
    null_mean = sum(nonzero) / 2.0
    standard_error = math.sqrt(sum(rank * rank for rank in nonzero) / 4.0)
    z_value = (positive - null_mean) / standard_error
    return {
        "statistic": min(positive, negative),
        "positive_rank_sum": positive,
        "negative_rank_sum": negative,
        "null_mean": null_mean,
        "standard_error": standard_error,
        "z_value": z_value,
        "raw_two_sided_p_value": math.erfc(abs(z_value) / math.sqrt(2.0)),
    }


def test_execution_identity_fingerprints_and_global_artifacts_are_locked() -> None:
    audit = _load()
    assert audit["schema_version"] == "phase6_m2_1_formal_test_results_v1_0"
    assert audit["provenance"] == {
        "output_root": "outputs/phase6_m2_1_formal_test_v1_0/formal/test",
        "pr74_merge_commit": "bcb3d91e3e0cf668b67057b0b8becbe0c252e4f4",
        "pr74_merge_tree": "8569866da6a81fc25c4d1fa163b55644e6ec5761",
        "execution_git_sha": "1688f504c1af276893682d3a38def4247fc53ad1",
        "execution_git_tree_sha": "8569866da6a81fc25c4d1fa163b55644e6ec5761",
        "execution_tree_equals_pr74_merge_tree": True,
        "working_tree_dirty": False,
        "untracked_execution_input_count_at_start": 0,
    }
    assert audit["fingerprints"] == {
        "scientific_config_sha256": "e277d43153f1a2f462423c6bd8ba25b0cd1931ff25dfcff3a34e69e3eb45aeaf",
        "e3_component_sha256": "e6444ac18bab5db5032860276e829af1b52103d9bbe92240ebecb8eb98fbf47c",
        "family_component_sha256": "67058c0aab89bdc6ca1722539320733ffc1b8c22e362599289f0e92bace740f5",
        "runner_config_sha256": "3cec059352dc14efb9c76748924b1815716ac0e68c07a4b8ab2b9b530c1c6333",
        "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
    }
    assert audit["formal_test_orchestrator_sha256"] == "e361b8031bcf4d81292c91d8482772d0154f25d69ded771c37215a59f40ff49b"
    assert audit["global_artifacts"] == {
        "formal_test_projection_sha256": "f8cb1865a3aa6f04fcc27b76c5464bf9c3e8ff2829039c4eb03e4a0b3423deb6",
        "formal_test_run_registry_sha256": "569e1a47687033060bf6f377f7f9ef245a976253b56caa9b6b257a2cba0f4232",
        "selected_plan_freeze_sha256": "59842e3eb1437ff5a16fa8980e79400dab6504ded032db6d30ef5e5f60302f90",
        "formal_test_reauthorization_sha256": "31d022833dd239793224aee799498374f1c471459045cc39328d0beebad38085",
    }


def test_ten_runs_sixty_plans_and_scenario_identities_close_independently() -> None:
    audit = _load()
    runs = audit["runs"]
    assert len(runs) == 10
    expected_cases = {
        f"M2_1_formal_triplet{index:02d}_train20260901{index:02d}_validation20260902{index:02d}_test20260903{index:02d}"
        for index in range(1, 11)
    }
    assert {run["case_id"] for run in runs} == expected_cases
    artifact_mapping = {}
    science_mapping = {}
    scenario_mapping = {}
    scenario_sets = set()
    complete_identities = set()
    evaluation_count = 0
    for index, run in enumerate(runs, 1):
        assert run["status"] == "optimal"
        assert run["training_seed"] == 2026090100 + index
        assert run["validation_seed"] == 2026090200 + index
        assert run["test_seed"] == 2026090300 + index
        assert run["selected_candidate_id"] in {"minimum_endpoint", "maximum_endpoint"}
        assert run["git_sha"] == audit["provenance"]["execution_git_sha"]
        assert run["git_tree_sha"] == audit["provenance"]["execution_git_tree_sha"]
        for field in ("result_sha256", "manifest_sha256", "status_summary_sha256"):
            assert SHA256.fullmatch(run[field])
        assert set(run["strategies"]) == set(STRATEGIES)
        identity = run["test_scenario_identity"]
        assert set(identity) == set(IDENTITY_FIELDS)
        assert all(SHA256.fullmatch(identity[field]) for field in IDENTITY_FIELDS)
        scenario_sets.add(identity["scenario_set_sha256"])
        complete_identities.add(_canonical_sha(identity))
        for strategy_id, strategy in run["strategies"].items():
            assert strategy["source_run_id"] == run["source_run_id"]
            assert strategy["source_case_id"] == run["case_id"]
            plan = strategy["plan_identity"]
            assert SHA256.fullmatch(plan["finalized_plan_artifact_sha256"])
            assert SHA256.fullmatch(plan["regular_purchase_sha256"])
            assert SHA256.fullmatch(plan["training_joint_scenario_set_sha256"])
            metrics = strategy["metrics"]
            assert metrics["plan_oos_status"] == "complete_feasible"
            assert metrics["total_scenario_count"] == 2000
            assert metrics["optimal_scenario_count"] == 2000
            assert metrics["infeasible_scenario_count"] == 0
            assert metrics["solver_failure_count"] == 0
            evaluation_count += metrics["optimal_scenario_count"]
            assert strategy["wall_seconds"] > 0
            assert SHA256.fullmatch(strategy["cross_item_allocation"]["scenario_item_emergency_spend_sha256"])
        minimum = run["strategies"]["M2_minimum_endpoint"]
        selected = run["strategies"]["M2_1_validation_selected_endpoint"]
        expected_difference = selected["metrics"]["total_cost_cvar95"] - minimum["metrics"]["total_cost_cvar95"]
        assert math.isclose(run["primary_cvar95_difference_m2_1_minus_m2"], expected_difference, abs_tol=1e-15)
        if run["selected_candidate_id"] == "minimum_endpoint":
            assert selected["plan_identity"] == minimum["plan_identity"]
            assert expected_difference == 0.0
        artifact_mapping[run["case_id"]] = {
            "run_id": run["run_id"],
            "result_sha256": run["result_sha256"],
            "manifest_sha256": run["manifest_sha256"],
            "status_summary_sha256": run["status_summary_sha256"],
        }
        science_mapping[run["case_id"]] = run["strategies"]
        scenario_mapping[run["case_id"]] = identity
    assert len(scenario_sets) == len(complete_identities) == 10
    assert evaluation_count == 120000
    assert _canonical_sha(artifact_mapping) == "277c3ef61db5d380d6a08a5c2c1b8163137e2769337da232a3cceda9832aae5f"
    assert _canonical_sha(science_mapping) == "22e1793200c17992f9d168c38ade739cb6039c7707ee4f26b00902a33b45c5d4"
    assert _canonical_sha(scenario_mapping) == "9d542ca0620dcc184ef3c3585e0a8d2f1b45e53c2d6ec8688ff0f831a12bf03d"


def test_primary_analysis_is_recomputed_from_seed_level_pairs() -> None:
    audit = _load()
    differences = [run["primary_cvar95_difference_m2_1_minus_m2"] for run in audit["runs"]]
    analysis = audit["primary_analysis"]
    assert differences == analysis["paired_differences"]
    values = np.asarray(differences, dtype=float)
    assert math.isclose(analysis["paired_mean_difference"], float(values.mean()), abs_tol=1e-15)
    assert math.isclose(analysis["paired_median_difference"], float(np.median(values)), abs_tol=1e-15)
    rng = np.random.Generator(np.random.PCG64DXSM(2026090999))
    bootstrap_means = values[rng.integers(0, 10, size=(10000, 10))].mean(axis=1)
    expected_ci = np.percentile(bootstrap_means, [2.5, 97.5], method="linear")
    assert np.allclose(analysis["bootstrap"]["percentile_95_ci"], expected_ci, atol=1e-15)
    expected_wilcoxon = _wilcoxon_pratt(differences)
    for field, expected in expected_wilcoxon.items():
        assert math.isclose(analysis["wilcoxon"][field], expected, abs_tol=1e-15)
    assert analysis["frozen_support_rule_passed"] is bool(
        values.mean() < 0 and expected_ci[1] < 0
    )
    m2 = np.mean([run["strategies"]["M2_minimum_endpoint"]["metrics"]["total_cost_cvar95"] for run in audit["runs"]])
    m21 = np.mean([run["strategies"]["M2_1_validation_selected_endpoint"]["metrics"]["total_cost_cvar95"] for run in audit["runs"]])
    assert math.isclose(analysis["m2_mean_cvar95"], m2, abs_tol=1e-12)
    assert math.isclose(analysis["m2_1_mean_cvar95"], m21, abs_tol=1e-12)
    assert abs(analysis["relative_mean_cvar95_difference_percent"]) < 0.001
    assert analysis["interpretation_boundary"] == "directionally_supported_but_practically_negligible_in_observed_scale"


def test_csv_aggregate_gates_and_stop_boundary_are_closed() -> None:
    audit = _load()
    with CSV_PATH.open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == 10
    by_case = {run["case_id"]: run for run in audit["runs"]}
    for row in csv_rows:
        run = by_case[row["case_id"]]
        assert int(row["training_seed"]) == run["training_seed"]
        assert int(row["test_seed"]) == run["test_seed"]
        assert math.isclose(float(row["difference_m2_1_minus_m2"]), run["primary_cvar95_difference_m2_1_minus_m2"], abs_tol=1e-15)
    aggregate = audit["aggregate"]
    assert aggregate["completed_primary_run_count"] == 10
    assert aggregate["completed_plan_count"] == 60
    assert aggregate["completed_exact_recourse_evaluation_count"] == 120000
    assert aggregate["selected_maximum_endpoint_count"] == 8
    assert aggregate["selected_minimum_endpoint_count"] == 2
    assert math.isclose(aggregate["total_wall_seconds"], sum(run["wall_seconds"] for run in audit["runs"]), abs_tol=1e-12)
    assert math.isclose(aggregate["maximum_peak_memory_mb"], max(run["peak_memory_mb"] for run in audit["runs"]), abs_tol=1e-12)
    for field in ("failed_primary_run_ids", "invalid_primary_run_ids", "duplicate_case_ids", "diagnostic_run_ids", "finalization_failure_run_ids"):
        assert aggregate[field] == []
    assert audit["gates"] == {
        "projection_status": "complete",
        "formal_test_gate_passed": True,
        "formal_extension_authorized": False,
        "algorithm_performance_authorized": False,
        "next_decision": "formal_test_results_review_only",
    }
    assert audit["execution_counts_outside_this_batch"] == {
        "new_scenario_generation_after_batch": 0,
        "new_gurobi_calls_after_batch": 0,
        "algorithm_performance_runs": 0,
        "M0_E3_runs": 0,
    }
    assert audit["CI"] == "recorded_in_pr_body"
