from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import statistics

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    ROOT
    / "docs/handoffs/2026-08-21_phase6_m2_formal_oos_results_v1_1_audit.json"
)
SOURCE_AUDIT_PATH = (
    ROOT
    / "docs/handoffs/2026-08-21_phase6_m2_formal_mechanism_results_v1_1_audit.json"
)
STRATEGIES = (
    "endogenous_reserve",
    "zero_autonomous_reserve",
    "fixed_autonomous_reserve_0_10",
    "fixed_autonomous_reserve_0_30",
    "fixed_autonomous_reserve_0_50",
)
FIXED_STRATEGIES = (
    ("fixed_autonomous_reserve_0_10", 0.1),
    ("fixed_autonomous_reserve_0_30", 0.3),
    ("fixed_autonomous_reserve_0_50", 0.5),
)
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": (
        "02d50abd609acd9d93eca6b13f6195e6eee14330e3db5c5ca75e83d2e7b56612"
    ),
    "e3_component_sha256": (
        "87f643fd3bf90f825251641c1bdeeb25f4aebb1ea23d052913b27e0b5fdf2924"
    ),
    "family_component_sha256": (
        "b1f9278ee8a0085e80c418f33d04c92b943c215eaf9ca2cdb6144e8dcebdb68b"
    ),
    "runner_config_sha256": (
        "c8d9efb59649b2a3e16839cdece7c38bc5a385358c354b72310c32134f49ad8e"
    ),
    "environment_sha256": (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    ),
}
CONTRAST_SPECS = (
    ("endogenous_minus_zero_mean_total_cost", "zero_autonomous_reserve", "mean_total_cost"),
    ("endogenous_minus_zero_total_cost_cvar95", "zero_autonomous_reserve", "total_cost_cvar95"),
    ("endogenous_minus_zero_service_level", "zero_autonomous_reserve", "service_level"),
    ("endogenous_minus_best_fixed_mean_total_cost", "best_fixed", "mean_total_cost"),
    ("endogenous_minus_best_fixed_total_cost_cvar95", "best_fixed", "total_cost_cvar95"),
)


def _load() -> dict:
    return json.loads(AUDIT_PATH.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        average = (start + 1 + end) / 2.0
        for position in range(start, end):
            ranks[order[position]] = average
        start = end
    return ranks


def _wilcoxon_pratt_approx(differences: list[float]) -> dict[str, float]:
    if all(value == 0 for value in differences):
        return {
            "statistic": 0.0,
            "z_statistic": 0.0,
            "raw_two_sided_p_value": 1.0,
            "positive_rank_sum": 0.0,
            "negative_rank_sum": 0.0,
            "null_mean": 0.0,
            "standard_error": 0.0,
        }
    absolute = [abs(value) for value in differences]
    ranks = _average_ranks(absolute)
    positive = sum(
        rank for rank, value in zip(ranks, differences, strict=True) if value > 0
    )
    negative = sum(
        rank for rank, value in zip(ranks, differences, strict=True) if value < 0
    )
    count = len(differences)
    zero_count = sum(value == 0 for value in differences)
    null_mean = (
        count * (count + 1) / 4.0
        - zero_count * (zero_count + 1) / 4.0
    )
    variance_numerator = (
        count * (count + 1) * (2 * count + 1)
        - zero_count * (zero_count + 1) * (2 * zero_count + 1)
    )
    tie_correction = sum(
        size**3 - size
        for value in set(absolute)
        if value != 0
        for size in [absolute.count(value)]
    )
    standard_error = math.sqrt(
        (variance_numerator - tie_correction / 2.0) / 24.0
    )
    z_statistic = (positive - null_mean) / standard_error
    return {
        "statistic": min(positive, negative),
        "z_statistic": z_statistic,
        "raw_two_sided_p_value": math.erfc(
            abs(z_statistic) / math.sqrt(2.0)
        ),
        "positive_rank_sum": positive,
        "negative_rank_sum": negative,
        "null_mean": null_mean,
        "standard_error": standard_error,
    }


def test_execution_identity_artifacts_and_source_binding_are_exact() -> None:
    audit = _load()
    assert audit["status"] == "complete"
    assert audit["execution_source"] == {
        "git_sha": "9f651265e1db3f67dfe221b1ff3409ddc8804480",
        "git_tree_sha": "27614de762cadc47acf65883e2c892dae9b53141",
        "merged_main_sha": "9f651265e1db3f67dfe221b1ff3409ddc8804480",
        "merged_main_tree_sha": "27614de762cadc47acf65883e2c892dae9b53141",
        "working_tree_dirty_at_start": False,
        "untracked_execution_input_count_at_start": 0,
    }
    assert audit["fingerprints"] == EXPECTED_FINGERPRINTS
    assert audit["formal_OOS_orchestrator_sha256"] == (
        "9628804bcc5fa12ef9e0a8f7652ccce274eb975772fbacd974978fe24c310113"
    )
    source = audit["source_reviewed_mechanism_evidence"]
    assert _sha256(SOURCE_AUDIT_PATH) == source["audit_sha256"] == (
        "bce5b075d352a4679b4371a073f5cc0a931a6b309b401318e9f4c38a8a7489a5"
    )
    assert source["registry_sha256"] == (
        "d418a1a10e9a995365f38f0110c682fb70e709a7deb8127ec039d5d9f0958eb3"
    )
    assert source["progress_sha256"] == (
        "5b02066db0a1bbe205042a9ab7abd454b678c81643e38c50459681e2ce5cab6e"
    )
    assert audit["global_artifacts"] == {
        "formal_OOS_run_registry_sha256": (
            "d07cd9fc5e0db04cd19b8785fd5b5583c07f787fc17565fa6c0d64a3306b1500"
        ),
        "formal_OOS_progress_sha256": (
            "f04245e2ded8bee6027392d0496ec8fded92a4350f0b57557e10026ec056034a"
        ),
    }


def test_each_oos_plan_is_bound_to_the_reviewed_pr58_source_plan() -> None:
    audit = _load()
    source_audit = json.loads(SOURCE_AUDIT_PATH.read_text(encoding="utf-8"))
    source_runs = {
        row["run_id"]: row
        for row in source_audit["runs"]
        if row["beta"] == 1.1 and row["profile_id"] == "T03"
    }
    assert len(source_runs) == 10
    assert {row["seed"] for row in source_runs.values()} == set(
        range(2026081401, 2026081411)
    )

    test_scenario_hashes = set()
    for row in audit["runs"]:
        source = source_runs[row["source_mechanism_run_id"]]
        assert source["run_id"] == row["source_mechanism_run_id"]
        assert source["seed"] == row["training_seed"]
        assert source["beta"] == row["beta"] == 1.1
        assert source["profile_id"] == row["profile_id"] == "T03"
        assert source["tier_id"] == row["tier_id"] == "M2F2"
        assert source["artifacts"]["result_sha256"] == row[
            "source_mechanism_result_sha256"
        ]
        assert source["science"]["joint_scenario_set_sha256"] == row[
            "source_training_joint_scenario_set_sha256"
        ]

        source_plans = source["science"]["first_stage_plan_identities"]
        assert set(source_plans) == set(STRATEGIES)
        for strategy_id in STRATEGIES:
            source_plan = source_plans[strategy_id]
            observed = row["strategy_results"][strategy_id][
                "source_plan_identity"
            ]
            assert source_plan["strategy_id"] == strategy_id
            assert observed == {
                "finalized_plan_artifact_sha256": source_plan[
                    "finalized_plan_artifact_sha256"
                ],
                "regular_purchase_sha256": source_plan[
                    "regular_purchase_sha256"
                ],
                "reserve_amount": source_plan["reserve_amount"],
                "exact_training_objective": source_plan[
                    "exact_training_objective"
                ],
                "training_joint_scenario_set_sha256": source_plan[
                    "training_joint_scenario_set_sha256"
                ],
            }
            assert source_plan["training_joint_scenario_set_sha256"] == row[
                "source_training_joint_scenario_set_sha256"
            ]

        assert row["git_sha"] == audit["execution_source"]["git_sha"]
        assert row["git_tree_sha"] == audit["execution_source"]["git_tree_sha"]
        assert row["formal_OOS_orchestrator_sha256"] == audit[
            "formal_OOS_orchestrator_sha256"
        ]
        test_scenario_hashes.add(row["test_joint_scenario_set_sha256"])

    assert len(test_scenario_hashes) == 10


def test_ten_runs_fifty_plans_and_source_plan_identities_recompute() -> None:
    audit = _load()
    runs = audit["runs"]
    assert len(runs) == 10
    assert {row["training_seed"] for row in runs} == set(
        range(2026081401, 2026081411)
    )
    assert {row["test_seed"] for row in runs} == set(
        range(2026081501, 2026081511)
    )
    for row in runs:
        seed = row["training_seed"]
        assert row["test_seed"] == seed + 100
        assert row["run_id"] == (
            "formal_oos_v1_1_20260821_M2F2_formal_OOS_"
            f"train{seed}_test{seed + 100}_beta1p10_profileT03"
        )
        assert row["case_id"] == (
            f"M2F2_formal_OOS_train{seed}_test{seed + 100}_"
            "beta1p10_profileT03"
        )
        assert row["tier_id"] == "M2F2"
        assert row["status"] == "optimal"
        assert row["parent_run_id"] is None
        assert row["beta"] == 1.1 and row["profile_id"] == "T03"
        assert math.isclose(
            row["budget"], row["beta"] * row["reference_budget"], abs_tol=1e-9
        )
        assert row["test_scenario_identity_count"] == 2000
        assert row["solver"] == "gurobi_direct"
        assert row["versions"] == {
            "gurobi_optimizer": "13.0.2",
            "gurobipy": "13.0.2",
        }
        assert row["threads"] == 1
        assert row["execution_limits"] == {
            "solver_call_seconds": 120.0,
            "OOS_plan_wall_seconds": 7200.0,
            "threads": 1,
        }
        assert row["fingerprints"] == EXPECTED_FINGERPRINTS
        assert set(row["strategy_results"]) == set(STRATEGIES)
        assert all(
            len(value) == 64 and int(value, 16) >= 0
            for value in row["artifacts"].values()
        )
        for strategy_id, strategy in row["strategy_results"].items():
            identity = strategy["source_plan_identity"]
            assert len(identity["finalized_plan_artifact_sha256"]) == 64
            assert len(identity["regular_purchase_sha256"]) == 64
            assert len(identity["training_joint_scenario_set_sha256"]) == 64
            assert (
                identity["training_joint_scenario_set_sha256"]
                == row["source_training_joint_scenario_set_sha256"]
            )
            metrics = strategy["metrics"]
            assert metrics["plan_oos_status"] == "complete_feasible"
            assert metrics["total_scenario_count"] == 2000
            assert metrics["optimal_scenario_count"] == 2000
            assert metrics["infeasible_scenario_count"] == 0
            assert metrics["solver_failure_count"] == 0
            for field in (
                "mean_total_cost",
                "total_cost_p95",
                "total_cost_cvar95",
                "service_level",
                "shortage_probability",
                "mean_emergency_spend",
            ):
                assert math.isfinite(metrics[field])
            assert 0 <= metrics["service_level"] <= 1
            assert 0 <= metrics["shortage_probability"] <= 1
            cross = strategy["cross_item_allocation"]
            assert len(cross["scenario_item_emergency_spend_sha256"]) == 64
            assert 0 <= cross["positive_total_emergency_spend_scenario_count"] <= 2000
            assert 0 <= cross["item1_emergency_spend_share_range"] <= 1

    artifact_mapping = {row["run_id"]: row["artifacts"] for row in runs}
    expected_artifact_mapping = (
        "5601c81267268ab70014d2de84065410c0ab8c396fd9ec9f6add7625315a145d"
    )
    assert _canonical_sha256(artifact_mapping) == expected_artifact_mapping
    assert audit["run_artifact_mapping_sha256"] == expected_artifact_mapping
    science_mapping = {
        row["run_id"]: {
            "source_mechanism_run_id": row["source_mechanism_run_id"],
            "source_mechanism_result_sha256": row[
                "source_mechanism_result_sha256"
            ],
            "source_training_joint_scenario_set_sha256": row[
                "source_training_joint_scenario_set_sha256"
            ],
            "test_joint_scenario_set_sha256": row[
                "test_joint_scenario_set_sha256"
            ],
            "strategies": {
                strategy_id: row["strategy_results"][strategy_id][
                    "source_plan_identity"
                ]
                for strategy_id in STRATEGIES
            },
        }
        for row in runs
    }
    expected_science_mapping = (
        "110ebd9ea0593edff9653367cf1b22fa5925488460355d29eabc450eab7903d7"
    )
    assert _canonical_sha256(science_mapping) == expected_science_mapping
    assert audit["science_evidence_mapping_sha256"] == expected_science_mapping


def test_counts_failures_resource_aggregates_and_stop_boundary_recompute() -> None:
    audit = _load()
    runs = audit["runs"]
    aggregate = audit["aggregate"]
    assert aggregate["required_primary_run_count"] == len(runs) == 10
    assert aggregate["completed_primary_run_count"] == sum(
        row["status"] == "optimal" for row in runs
    )
    assert aggregate["completed_plan_count"] == sum(
        len(row["strategy_results"]) for row in runs
    ) == 50
    assert aggregate["completed_exact_recourse_evaluation_count"] == sum(
        strategy["metrics"]["optimal_scenario_count"]
        for row in runs
        for strategy in row["strategy_results"].values()
    ) == 100000
    assert aggregate["infeasible_scenario_count"] == sum(
        strategy["metrics"]["infeasible_scenario_count"]
        for row in runs
        for strategy in row["strategy_results"].values()
    ) == 0
    assert aggregate["solver_failure_count"] == sum(
        strategy["metrics"]["solver_failure_count"]
        for row in runs
        for strategy in row["strategy_results"].values()
    ) == 0
    assert math.isclose(
        aggregate["total_wall_seconds"],
        sum(row["wall_seconds"] for row in runs),
        abs_tol=1e-12,
    )
    assert aggregate["maximum_run_wall_seconds"] == max(
        row["wall_seconds"] for row in runs
    )
    assert aggregate["maximum_peak_memory_mb"] == max(
        row["peak_memory_mb"] for row in runs
    )
    for field in (
        "missing_case_ids",
        "invalid_primary_run_ids",
        "failed_primary_run_ids",
        "duplicate_case_ids",
        "diagnostic_run_ids",
        "finalization_failure_run_ids",
    ):
        assert aggregate[field] == []
    assert audit["machine_gate"] == {
        "formal_OOS_gate_passed": True,
        "next_decision": "permit_OOS_results_review_only",
        "algorithm_performance_authorized": False,
        "formal_extension_complete": False,
    }
    assert audit["scope"]["algorithm_performance_runs"] == 0
    assert audit["scope"]["M0_E3_runs"] == 0


def test_frozen_best_fixed_selection_and_primary_statistics_recompute() -> None:
    audit = _load()
    runs = {row["training_seed"]: row for row in audit["runs"]}
    analysis = audit["formal_OOS_statistical_analysis"]
    best_fixed: dict[int, str] = {}
    for seed, row in runs.items():
        best_fixed[seed] = min(
            (
                row["strategy_results"][strategy_id]["source_plan_identity"][
                    "exact_training_objective"
                ],
                rho,
                strategy_id,
            )
            for strategy_id, rho in FIXED_STRATEGIES
        )[2]
    assert analysis["best_fixed_strategy_selection"][
        "selected_by_training_seed"
    ] == {str(seed): value for seed, value in sorted(best_fixed.items())}
    assert analysis["bootstrap"] == {
        "method": "paired_cluster_percentile",
        "cluster_unit": "paired_training_test_seed_pair",
        "random_seed": 2026081499,
        "resamples": 10000,
        "confidence_level": 0.95,
        "point_estimator": (
            "arithmetic_mean_of_ten_seed_level_paired_differences"
        ),
        "implementation": "numpy.random.Generator(numpy.random.PCG64(seed))",
        "numpy_version": "2.5.1",
        "index_sampling": (
            "Generator.integers(0,10,size=(10000,10),endpoint=False)"
        ),
        "percentile_implementation": "numpy.percentile(method=linear)",
        "percentile_bounds": [2.5, 97.5],
    }

    raw_p_values: list[float] = []
    for observed, (contrast_id, comparator, metric) in zip(
        analysis["primary_contrasts"], CONTRAST_SPECS, strict=True
    ):
        differences = []
        expected_pairs = []
        for seed in sorted(runs):
            row = runs[seed]
            comparator_strategy = (
                best_fixed[seed] if comparator == "best_fixed" else comparator
            )
            treatment_value = row["strategy_results"]["endogenous_reserve"][
                "metrics"
            ][metric]
            comparator_value = row["strategy_results"][comparator_strategy][
                "metrics"
            ][metric]
            difference = treatment_value - comparator_value
            differences.append(difference)
            expected_pairs.append(
                {
                    "training_seed": seed,
                    "test_seed": row["test_seed"],
                    "treatment_strategy": "endogenous_reserve",
                    "comparator_strategy": comparator_strategy,
                    "metric": metric,
                    "treatment_value": treatment_value,
                    "comparator_value": comparator_value,
                    "paired_difference": difference,
                }
            )
        assert observed["contrast_id"] == contrast_id
        assert observed["paired_seed_differences"] == expected_pairs
        assert math.isclose(
            observed["arithmetic_mean_effect"],
            statistics.mean(differences),
            abs_tol=1e-15,
        )
        generator = np.random.Generator(np.random.PCG64(2026081499))
        values = np.asarray(differences, dtype=float)
        bootstrap_means = values[
            generator.integers(0, 10, size=(10000, 10), endpoint=False)
        ].mean(axis=1)
        expected_ci = np.percentile(
            bootstrap_means, [2.5, 97.5], method="linear"
        )
        assert np.allclose(
            observed["bootstrap_percentile_95_ci"], expected_ci, atol=1e-15
        )
        expected_wilcoxon = _wilcoxon_pratt_approx(differences)
        for field, value in expected_wilcoxon.items():
            assert math.isclose(
                observed["wilcoxon"][field], value, abs_tol=1e-15
            )
        raw_p_values.append(expected_wilcoxon["raw_two_sided_p_value"])

    order = sorted(range(5), key=lambda index: (raw_p_values[index], index))
    adjusted: list[float | None] = [None] * 5
    running_maximum = 0.0
    for rank, index in enumerate(order, start=1):
        running_maximum = max(
            running_maximum, min(1.0, (6 - rank) * raw_p_values[index])
        )
        adjusted[index] = running_maximum
        observed = analysis["primary_contrasts"][index]["wilcoxon"]
        assert observed["holm_rank"] == rank
        assert math.isclose(
            observed["holm_adjusted_p_value"],
            running_maximum,
            abs_tol=1e-15,
        )
        assert observed["holm_reject_at_familywise_alpha_0_05"] is (
            running_maximum <= 0.05
        )
