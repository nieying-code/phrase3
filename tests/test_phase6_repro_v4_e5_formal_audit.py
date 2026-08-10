"""Validate the compact Phase 6 reproducibility-v4 E5 formal audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


AUDIT = Path(
    "docs/handoffs/2026-08-10_phase6_repro_v4_e5_formal_audit.json"
)
SEEDS = list(range(2026072401, 2026072406))
CONFIGURATIONS = [
    "baseline",
    "ofat_demand_cv_0.15",
    "ofat_demand_cv_0.45",
    "ofat_emergency_price_markup_mean_0.15",
    "ofat_emergency_price_markup_mean_0.55",
    "ofat_supply_reduction_mean_0.05",
    "ofat_supply_reduction_mean_0.4",
    "ofat_shelf_life_periods_1",
    "ofat_shelf_life_periods_6",
    "ofat_storage_capacity_to_expected_period_demand_0.5",
    "ofat_storage_capacity_to_expected_period_demand_1.5",
    "interaction_life_1_supply_0.05",
    "interaction_life_1_supply_0.4",
    "interaction_life_6_supply_0.05",
    "interaction_life_6_supply_0.4",
]
EXPECTED_RUNS = {
    "formal_e5_repro_v4_v2_2026072401": (2026072401, "10b6be3a7e4d8bb84990a64d17f0e5db3cd235bda446a56cf46f58a72d26d903", "44eeae4147509a7f76e52af620fdebaff5649455bd01eef6461becf931d4c0a7", "d2c2359865705ecc6955c62452292419eec0d61af17398c837613755716c443d", "0f7d64e61525e222976551c1c98aab1cf4f0f056762ba15745e0f7089e35893c", "556fe0fbaa5d58ad3f74390bd1dacf52a555810b16224a576e4a1a59eddbeb8a"),
    "formal_e5_repro_v4_v2_2026072402": (2026072402, "eaf2f88f4fc91f2431b456b5330605436daff36fd01acafed6a630af4f053023", "88434a1575eda290ba9ba80cf0efd0a5b01dc647535d3496878c84a89e0e41cc", "8c0f8767a1c04fabad88fd6a6bc5ebf3e9cf947faa8b7775ef2fafaf7069950c", "fa3a8664e62bbee3e891294751aa4a7524dec5ab41147499add424a15f336100", "dfeec30b9f2593c86f0544dd616719f3c8c06167597075939f59e4ceeb960e93"),
    "formal_e5_repro_v4_v2_2026072403": (2026072403, "17a03ad52796b0d75b1e677f48fbd3b7b24a2bb696575e8881378622385203ae", "9421225f0cad1c847cffa5a393feecd2ae01fc62968ab6ea89ae117af6acb3d7", "1ba2d311b5144e293e64ec64f3a7c781865283a6ce5279c06b7c09ce3c4507d1", "b64547f64e2d81a5ccfebefdb8a2eeb1d7a5a8d7ae2c8d773dd47929095fa320", "bf32ddef789278d20d497204b4ff0e70e9a4a7ee93d3158b4c3e19c47fe6442f"),
    "formal_e5_repro_v4_v2_2026072404": (2026072404, "0c0635c1b864e5ee11d942fed8f41632ef8d0e8f8d72ddc15251e338039415b0", "7e5929c6aa20b70242abf6b2295b230ed33854b6a47f862ba6e06fd868f2c99f", "2fba27dd64a645115516eb89f7d8155b98e29560603224d2ccd215ec654182b7", "be827f735f41ad8b8972d78b17b0827249b11819b2b1f97c300761d7a61e37eb", "5c716e18dc6804a5bde441c0fc27fdbb74e7aa5071662f971945603c67191e81"),
    "formal_e5_repro_v4_v2_2026072405": (2026072405, "891360e3aef023a442eb3d012a390c3cd006751e5b02b12c7b5a159c13409ee7", "ef1be45b73256fdf6cb5f589ebfbc533630d877e262dfb9435d7d5cb29ab70fc", "dfd148ba3032711ff454587a7302dd5998db90bd969004b256e4ce9abe4c77b0", "83364597eba45bcdc2f0169070652158e1df5f1643c73f582f35b1c07a1db4cd", "a107cc085d9597c101ba7d8d5ed3c13db51a3dcfd1250465af3c3a6e6449a81d"),
}
EXPECTED_MEAN_OBJECTIVES = {
    "baseline": 21361.054897160313,
    "ofat_demand_cv_0.15": 8406.402084722758,
    "ofat_demand_cv_0.45": 36949.90961722295,
    "ofat_emergency_price_markup_mean_0.15": 19137.97698557961,
    "ofat_emergency_price_markup_mean_0.55": 23584.13280874101,
    "ofat_supply_reduction_mean_0.05": 21361.054897160313,
    "ofat_supply_reduction_mean_0.4": 21361.054897160313,
    "ofat_shelf_life_periods_1": 21790.102836821505,
    "ofat_shelf_life_periods_6": 21361.054897160313,
    "ofat_storage_capacity_to_expected_period_demand_0.5": 21699.337087678236,
    "ofat_storage_capacity_to_expected_period_demand_1.5": 21521.592212806478,
    "interaction_life_1_supply_0.05": 21790.102836821505,
    "interaction_life_1_supply_0.4": 21790.102836821505,
    "interaction_life_6_supply_0.05": 21361.054897160313,
    "interaction_life_6_supply_0.4": 21361.054897160313,
}


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_repro_v4_e5_formal_audit_is_complete_and_consistent() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    source = audit["source"]
    assert source["execution_git_sha"] == source["merged_main_git_sha"] == (
        "54d6ed0868b0ba47b3e7886714a75ab85f911084"
    )
    assert source["execution_git_tree_sha"] == source["merged_main_git_tree_sha"] == (
        "03216fc7c4d0de155c7770f652e8a5dd816fcf4a"
    )
    assert source["tracked_modified_count_at_start"] == 0
    assert source["untracked_execution_input_count_at_start"] == 0
    assert source["working_tree_dirty"] is False

    assert audit["fingerprints"] == {
        "scientific_config_sha256": "f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3",
        "family_config_sha256": "983776a19e0a12937bc8a185b0fe5fdf76877d266445dcfce5f252d397a6ca8c",
        "family_component_sha256": "92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e",
        "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
    }
    assert audit["environment"] == {
        "python": "3.12.10",
        "gurobipy": "13.0.2",
        "gurobi_optimizer": "13.0.2",
        "pyomo_interface": "gurobi_direct",
        "threads": 1,
        "highs_fallback": False,
    }

    design = audit["design"]
    assert design["tier_id"] == "V2"
    assert design["training_seeds"] == SEEDS
    assert design["budget_factor"] == 1.1
    assert design["budget"] == 1353.3536929340091
    assert design["ofat_configuration_count"] == 11
    assert design["interaction_configuration_count"] == 4
    assert design["configuration_ids"] == CONFIGURATIONS

    runs = {row["run_id"]: row for row in audit["runs"]}
    assert set(runs) == set(EXPECTED_RUNS)
    for run_id, expected in EXPECTED_RUNS.items():
        seed, result_hash, manifest_hash, status_hash, plan_hash, worker_hash = expected
        row = runs[run_id]
        assert row["tier_id"] == "V2"
        assert row["training_seed"] == seed
        assert row["execution_mode"] == "formal"
        assert row["status"] == "optimal"
        assert row["planned_work_units"] == row["completed_work_units"] == 15
        assert row["parent_run_id"] == ""
        assert row["result_sha256"] == result_hash
        assert row["manifest_sha256"] == manifest_hash
        assert row["status_summary_sha256"] == status_hash
        assert row["worker_result_map_sha256"] == worker_hash
        expected_plan_ids = sorted(
            f"E5_V2_{seed}_{configuration_id}"
            for configuration_id in CONFIGURATIONS
        )
        assert _canonical_sha256(expected_plan_ids) == row["plan_identity_sha256"] == plan_hash

    counts = audit["counts"]
    assert len(runs) == counts["primary_run_count"] == counts["optimal_primary_run_count"] == 5
    assert 5 * 15 == counts["planned_work_unit_count"] == counts["completed_work_unit_count"] == counts["optimal_work_unit_count"] == 75
    for field in (
        "positive_reserve_plan_count",
        "failed_primary_run_count",
        "failed_work_unit_count",
        "duplicate_primary_run_count",
        "parent_run_count",
        "diagnostic_attempt_count",
    ):
        assert counts[field] == 0

    summaries = audit["configuration_summaries"]
    assert set(summaries) == set(CONFIGURATIONS)
    assert {
        key: row["mean_robust_objective"] for key, row in summaries.items()
    } == EXPECTED_MEAN_OBJECTIVES
    assert _canonical_sha256(summaries) == (
        "db8e659700113eb406626d04ddc4b597c815d1126154296967e620e32a08d556"
    )
    for row in summaries.values():
        assert row["count"] == row["optimal_count"] == 5
        assert row["positive_reserve_count"] == 0
        assert row["mean_reserve"] == row["maximum_reserve"] == 0.0
        assert row["mean_reserve_ratio"] == 0.0
        assert row["minimum_robust_objective"] <= row["mean_robust_objective"]
        assert row["mean_robust_objective"] <= row["maximum_robust_objective"]

    finding = audit["mechanism_finding"]
    assert finding["reserve_activation_tolerance"] == 1e-7
    assert finding["plan_count"] == 75
    assert finding["positive_reserve_plan_count"] == 0
    assert finding["maximum_reserve"] == 0.0
    assert finding["configuration_count_with_any_positive_reserve"] == 0
    assert finding["frozen_range_supports_positive_endogenous_reserve"] is False
    baseline = summaries["baseline"]["mean_robust_objective"]
    assert summaries["ofat_supply_reduction_mean_0.05"]["mean_robust_objective"] == baseline
    assert summaries["ofat_supply_reduction_mean_0.4"]["mean_robust_objective"] == baseline
    assert summaries["ofat_demand_cv_0.15"]["mean_robust_objective"] < baseline
    assert summaries["ofat_demand_cv_0.45"]["mean_robust_objective"] > baseline

    assert audit["execution_observer_event"] == {
        "outer_serial_observer_timeout_seconds": 120,
        "finalized_before_observer_timeout_run_count": 4,
        "fifth_run_started_before_observer_timeout": False,
        "fifth_run_later_started_once_with_original_planned_run_id": True,
        "same_run_id_retry_count": 0,
        "scientific_failure": False,
    }
    assert audit["formal_primary_run_count_by_family_after_batch"] == {
        "E1": 14,
        "E2": 10,
        "E4": 5,
        "E5": 5,
    }
    assert audit["global_artifacts"] == {
        "family_run_registry_sha256": "f61805a6cec93193f9b279853895f781035dd4a498387d8ad3b9b33346a5bb4d",
        "algorithm_performance_sha256": "2486b070ee569bcc938cdb2468eb173d658353fd181c286bdaccf6216cb791c3",
        "pilot_throughput_projection_sha256": "c3b9c26e69a46aa89a99d7b6f40ff307c308c2782405e884154bc21c906faff2",
    }
    assert audit["authorization_after_batch"] == {
        "projection_status": "passed",
        "compute_gate_passed": True,
        "formal_execution_authorized": True,
    }
    assert audit["stop_boundary"] == {
        "e3_formal_started_in_batch": False,
        "additional_formal_family_started": False,
    }
