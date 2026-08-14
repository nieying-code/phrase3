import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-14_phase6_m2_formal_extension_pilot_v1_1_audit.json"
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": "02d50abd609acd9d93eca6b13f6195e6eee14330e3db5c5ca75e83d2e7b56612",
    "e3_component_sha256": "87f643fd3bf90f825251641c1bdeeb25f4aebb1ea23d052913b27e0b5fdf2924",
    "family_component_sha256": "b1f9278ee8a0085e80c418f33d04c92b943c215eaf9ca2cdb6144e8dcebdb68b",
    "runner_config_sha256": "c8d9efb59649b2a3e16839cdece7c38bc5a385358c354b72310c32134f49ad8e",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}
EXPECTED_GLOBAL_ARTIFACTS = {
    "pilot_run_registry_sha256": "4088a8782ad5990f5398407a01191a0cd30489b702d927a57e1df61048709b95",
    "pilot_projection_sha256": "111657c0b7a22a50cfd44eee677b0a1a2c0f6adb7299ce19b4f3b2258d4ba6ef",
}
EXPECTED_ARTIFACT_MAPPING_SHA256 = "0c8a42c38768c1591fdb70e8ef3a8e1c36bcd512ffea1f7274819893d416d544"
EXPECTED_SCIENCE_MAPPING_SHA256 = "1f65a299cc4e11df2fac4ce6ff206a4350b21fad39aa17fdaebcc998578bf051"
EXPECTED_OOS_SOURCE_PLAN_MAPPING_SHA256 = "a2288e2861fade5fa6f13ab13197a77b43d4cd9be2d302b41e51db910d058d20"
SEEDS = (2026081601, 2026081602, 2026081603)


def _canonical_sha256(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def _load():
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def test_execution_identity_and_exact_run_cartesian_product():
    audit = _load()
    execution = audit["execution"]
    assert execution["git_sha"] == "b1df27402fbd33c7e6f3a2eb1555398a6a9727e1"
    assert execution["git_tree_sha"] == "50f84608878d1fca42a5f9f8b8cc9a483374a7d2"
    assert execution["working_tree_dirty_at_start"] is False
    assert execution["tracked_modified_count_at_start"] == 0
    assert execution["untracked_execution_input_count_at_start"] == 0
    assert execution["python_version"] == "3.12.10"
    assert execution["gurobi_optimizer_version"] == "13.0.2"
    assert execution["gurobipy_version"] == "13.0.2"
    assert execution["pyomo_interface"] == "gurobi_direct"
    assert execution["threads"] == 1
    assert execution["execution_mode"] == "pilot"
    assert execution["strictly_serial"] is True
    assert audit["fingerprints"] == EXPECTED_FINGERPRINTS

    mechanism = [row for row in audit["runs"] if row["run_kind"] == "mechanism"]
    expected = {
        (seed, beta, profile)
        for seed in SEEDS
        for beta, profiles in ((1.1, ("C0", "C1", "T03")), (1.3, ("C0", "T03")))
        for profile in profiles
    }
    assert {(r["seed"], r["beta"], r["profile_id"]) for r in mechanism} == expected
    assert len(mechanism) == 15
    assert all(r["tier_id"] == "M2F2" and r["status"] == "optimal" and r["finalized"] for r in mechanism)
    assert all(r["parent_run_id"] is None for r in audit["runs"])

    oos = [row for row in audit["runs"] if row["run_kind"] == "oos_probe"]
    assert len(oos) == 1
    assert (oos[0]["seed"], oos[0]["test_seed"], oos[0]["beta"], oos[0]["profile_id"]) == (
        2026081601,
        2026081701,
        1.1,
        "T03",
    )
    assert oos[0]["status"] == "optimal" and oos[0]["finalized"] is True


def test_artifact_and_science_mappings_are_exactly_locked():
    audit = _load()
    artifact_mapping = {
        row["run_id"]: {
            field: row[field]
            for field in ("result_sha256", "manifest_sha256", "status_summary_sha256")
        }
        for row in audit["runs"]
    }
    science_mapping = {row["run_id"]: row["science"] for row in audit["runs"]}
    assert _canonical_sha256(artifact_mapping) == EXPECTED_ARTIFACT_MAPPING_SHA256
    assert audit["run_artifact_mapping_sha256"] == EXPECTED_ARTIFACT_MAPPING_SHA256
    assert _canonical_sha256(science_mapping) == EXPECTED_SCIENCE_MAPPING_SHA256
    assert audit["science_evidence_mapping_sha256"] == EXPECTED_SCIENCE_MAPPING_SHA256
    assert audit["global_artifacts"] == EXPECTED_GLOBAL_ARTIFACTS


def test_mechanism_science_and_common_random_numbers_close():
    audit = _load()
    mechanism = [row for row in audit["runs"] if row["run_kind"] == "mechanism"]
    for row in mechanism:
        science = row["science"]
        assert math.isclose(science["budget"], row["beta"] * science["reference_budget"], abs_tol=1e-9)
        assert science["training_scenario_count"] == science["scenario_identity_count"] == 100
        assert science["fixed_reserve_policy_count"] == 4
        assert math.isclose(
            science["R_disc_robust"],
            max(0.0, science["R_min_opt"] - science["R_min_feas"]),
            abs_tol=1e-12,
        )
        assert math.isclose(science["R_disc_robust_ratio"], science["R_disc_robust"] / science["budget"], abs_tol=1e-12)
        for field in ("minimum_endpoint_consistency_difference", "maximum_endpoint_consistency_difference"):
            value = science[field]
            assert math.isfinite(value) and value >= 0
            assert value <= science["objective_tolerance"] + 1e-8

    for seed in SEEDS:
        group = [r for r in mechanism if r["seed"] == seed]
        for field in ("latent_draw_sha256", "demand_sha256", "emergency_price_sha256", "emergency_supply_sha256", "scenario_order_sha256"):
            assert len({r["science"]["scenario_component_set_sha256"][field] for r in group}) == 1


def test_oos_probe_is_complete_and_source_bound():
    audit = _load()
    probe = audit["oos_probe"]
    expected_source = "m2formal_pilot_v1_1_20260814_M2F2_seed2026081601_beta1p10_profileT03"
    assert probe["source_mechanism_run_id"] == expected_source
    assert probe["source_mechanism_case_id"] == "M2F2_seed2026081601_beta1p10_profileT03"
    assert probe["source_mechanism_result_sha256"] == (
        "d93da98b12eb452be3a583666ba6ff2d11284c2f100607160a1406c08cdf596a"
    )
    assert probe["test_scenario_identity_count"] == 2000
    assert probe["test_joint_scenario_set_sha256"] == "3ba7c557e3dc330356bb8ce5169782a504d1ccc888851223b4ba32914018643d"
    assert set(probe["strategies"]) == {
        "endogenous_reserve",
        "zero_autonomous_reserve",
        "fixed_autonomous_reserve_0_10",
        "fixed_autonomous_reserve_0_30",
        "fixed_autonomous_reserve_0_50",
    }
    source_plans = probe["source_first_stage_plan_artifacts"]
    assert set(source_plans) == set(probe["strategies"])
    assert _canonical_sha256(source_plans) == EXPECTED_OOS_SOURCE_PLAN_MAPPING_SHA256
    assert audit["oos_source_plan_identity_mapping_sha256"] == EXPECTED_OOS_SOURCE_PLAN_MAPPING_SHA256
    for strategy_id, strategy in probe["strategies"].items():
        source = source_plans[strategy_id]
        assert source["strategy_id"] == strategy_id
        assert strategy["source_plan_artifact_sha256"] == source["finalized_plan_artifact_sha256"]
        assert strategy["regular_purchase_sha256"] == source["regular_purchase_sha256"]
        assert math.isclose(strategy["reserve"], source["reserve_amount"], abs_tol=1e-12)
        assert math.isclose(
            strategy["source_plan_exact_training_objective"],
            source["exact_training_objective"],
            abs_tol=1e-12,
        )
        assert strategy["source_plan_training_joint_scenario_set_sha256"] == (
            source["training_joint_scenario_set_sha256"]
        )
        assert strategy["source_plan_training_joint_scenario_set_sha256"] == (
            probe["source_training_joint_scenario_set_sha256"]
        )
        assert strategy["status"] == "complete_feasible"
        assert strategy["scenario_count"] == strategy["optimal_scenario_count"] == 2000
        assert strategy["infeasible_scenario_count"] == strategy["solver_failure_count"] == 0
        assert math.isfinite(strategy["wall_seconds"]) and strategy["wall_seconds"] > 0
        for field in ("mean_total_cost", "p95_total_cost", "cvar95_total_cost", "demand_weighted_service_level", "shortage_probability", "mean_emergency_spend"):
            assert math.isfinite(strategy[field])
        assert 0 <= strategy["demand_weighted_service_level"] <= 1
        assert 0 <= strategy["shortage_probability"] <= 1


def test_projection_and_stop_boundary_are_independently_recomputed():
    audit = _load()
    runs = audit["runs"]
    mechanism = [r for r in runs if r["run_kind"] == "mechanism"]
    probe = audit["oos_probe"]
    projection = audit["projection"]
    aggregate = audit["aggregate"]
    assert aggregate["completed_run_count"] == len(runs) == 16
    assert aggregate["mechanism_run_count"] == aggregate["mechanism_optimal_count"] == 15
    assert aggregate["oos_probe_run_count"] == aggregate["oos_probe_optimal_count"] == 1
    assert aggregate["oos_strategy_count"] == len(probe["strategies"]) == 5
    assert aggregate["oos_optimal_scenario_evaluation_count"] == 5 * 2000 == 10000
    assert aggregate["oos_infeasible_scenario_count"] == aggregate["oos_solver_failure_count"] == 0
    assert math.isclose(aggregate["total_wall_seconds"], sum(r["wall_seconds"] for r in runs), abs_tol=1e-9)
    assert aggregate["max_peak_memory_mb"] == max(r["peak_memory_mb"] for r in runs)
    assert projection["verified_mechanism_run_count"] == projection["required_mechanism_run_count"] == 15
    assert projection["verified_OOS_probe_run_count"] == projection["required_OOS_probe_run_count"] == 1
    for field in ("invalid_primary_run_ids", "diagnostic_run_ids", "duplicate_case_ids", "failed_primary_run_ids", "finalization_failure_run_ids"):
        assert projection[field] == []
    mechanism_rate = max(r["wall_seconds"] for r in mechanism)
    oos_rate = max(v["wall_seconds"] for v in probe["strategies"].values())
    assert math.isclose(projection["mechanism_seconds_per_formal_run"], mechanism_rate, abs_tol=1e-12)
    assert math.isclose(projection["OOS_seconds_per_formal_plan"], oos_rate, abs_tol=1e-12)
    assert math.isclose(projection["mechanism_projected_wall_hours"], 50 * mechanism_rate / 3600, abs_tol=1e-12)
    assert math.isclose(projection["OOS_projected_wall_hours"], 50 * oos_rate / 3600, abs_tol=1e-12)
    assert math.isclose(projection["combined_projected_wall_hours"], 1.329444276388838, abs_tol=1e-12)
    assert projection["pilot_compute_gate_passed"] is True
    assert projection["next_decision"] == "permit_separate_formal_freeze_PR_only"
    assert projection["formal_extension_authorized"] is False
    assert audit["stop_boundary"] == {
        "pilot_compute_gate_passed": True,
        "next_decision": "permit_separate_formal_freeze_PR_only",
        "formal_extension_authorized": False,
        "formal_mechanism_runs_started": 0,
        "formal_oos_evaluations_started": 0,
        "m0_e3_runs_started": 0,
    }
