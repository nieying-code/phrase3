"""Validate the compact Phase 6 reproducibility-v4 E2 formal audit."""

from __future__ import annotations

import json
import hashlib
from collections import Counter
from pathlib import Path


AUDIT = Path(
    "docs/handoffs/2026-08-10_phase6_repro_v4_e2_formal_audit.json"
)
EXPECTED_BUDGETS = [
    1107.2893851278257,
    1353.3536929340091,
    1599.4180007401926,
]
EXPECTED_POLICIES = [
    "deterministic_mean",
    "zero_reserve",
    "fixed_reserve_0_10",
    "fixed_reserve_0_30",
    "fixed_reserve_0_50",
    "endogenous_reserve",
]
EXPECTED_RUNS = {
    "formal_e2_repro_v4_v2_2026072401": (2026072401, "ee894a86fee6872c973881a329eb584138c186375ed4033abaeea8e656e0bbec", "02072d40a59ac83f9a33c310ca7820c9d73bb06453a721172ae3f7fa89c6d565", "0ac59715e6d3c846a8116366fec01fb8ce5216e715a51dff73c727b3119a0a18", "4c0e0b21f55e9f52c02c3ad2be5c0d77256794a68b569d88b73abe3b3c55a854"),
    "formal_e2_repro_v4_v2_2026072402": (2026072402, "49b8e7670d5c9e408a4d61d276922245edd4d45efe6ec5bbbd0abfdc2ea0df7d", "88eddd2b3cbae96440980ca7acf275f6ff5c0d8ebbb8ca47d54b0e80faea105b", "74c85bb8714d3c117969f51b6b593e8d21a9e1579c0ebd99311b0126a3ad6973", "691d21c5b12c8927593ebd83cb02ec1678b172ecfb0cdd280f81033105450171"),
    "formal_e2_repro_v4_v2_2026072403": (2026072403, "d792dd29b64b389bcbb53ddde036e3b97971d5f71be541959fdbde616bb53a12", "e13998c533c8ea2f9919735cf0c33bb85addd241782b4dd3a02bbfd207a5eb22", "3a3cbec9605fc4151788010f40196b70ff2eef66c04138fe0e47240689bffc88", "84fb01d37a41d6ae6835972ec3dc7a5f0c7c8d11ee3eeea44038420d0840ba69"),
    "formal_e2_repro_v4_v2_2026072404": (2026072404, "b57b4d6b7b2c09e6c1825036876b8a349090e9266c013ea3f231a86d9baa4516", "7102b48dcd8ce8968e27f7b3af8bbe9f5c145de37b9f4f1349f9977d6945c53e", "7fe6339945e96a9374ad36c7657628c600a5269419d5b7a2d42788d333c4983c", "9e9abda2c3f12e43dd9257c5bd9a06c3672fa8e48406d246b4a70129241a7a9b"),
    "formal_e2_repro_v4_v2_2026072405": (2026072405, "693499e4b2d60625d84cc289e374d01e3ede02395eb242545c928196de8a4823", "f00f0acbeb060839d0bb3238ab61bd41ce343606a803c746d6fa580a88915645", "2ea9b589bdf6203d459a29c643d0fba46a07b2d828c92574f319551d77a0bc2c", "4c5f722e4fd7a221285113524a1a852ab8e047d6e0a018e368dee935dd6a6dd6"),
    "formal_e2_repro_v4_v2_2026072406": (2026072406, "0dd27d200767267ee6423b9f48dab98cf48a355881594a89d40a3adcbc278d5c", "d0bc93f0b1d047dd3545d1026a3ec021fb45b4270231dd10f05b08d74e1dfdc0", "a1d5f8e5e9cd97e7f2639acefefd3c1bda01db00b7aa92908f237132409588bb", "b670777dc33b40cdf6216356e12ccb6ad2a1482cc0b928e04db1acd254c067f3"),
    "formal_e2_repro_v4_v2_2026072407": (2026072407, "580e3a48553a7c7d479a708977ce62d0627a7d3e8f1138b91bcaff5f5c94e0aa", "0bd38f2bf09da2adbe24d5a12ed6458ef20be555a319e818ef996c33fd6654a2", "2bdccf5e780781b44171d6d6637d0cee9309399e8a14bd26209e77da7b330792", "3a6ee78680be2230c6cd9b1a694b757e8e64902a2162c4e1fa431da5cc7eaebf"),
    "formal_e2_repro_v4_v2_2026072408": (2026072408, "512538ec7731922dbddfce366f3714c31122ad4c1440c6377f225effa8e7d5ed", "8da2a35f12aa450f5dd872b3053650058808330a0522f4a4e60b31b36b5a9da3", "a6bf393a93648d1c301b759ffd615ad2a5c19950b5bd34a7e2bcd21744b48a2d", "265528c1669ca4c0ebfbafe3e9d03d7ffe33a3e307d717edd49d373312878882"),
    "formal_e2_repro_v4_v2_2026072409": (2026072409, "1c60852ae80011ad174f9aa21d67b14cc9289faeef36bb4cd7e4fbaf0aa9dcfc", "e1f1b4fab756ad216cd17fe6b9820e79dd28b88aad0acb43799cea1c8b8d12f3", "828b27a7e7dbeb099cf18673a9d5e5eb8feecae406d3df564ab7d2cb1b428a70", "bc3d2fb273df3cb482d2aee2b9b4646abb052c99ff2db463bc6e4661c7776ad2"),
    "formal_e2_repro_v4_v2_2026072410": (2026072410, "562bf8f9b32c8d79a52ae032ce4f3099d89f63539ad349ca7f5b84cf8dbd000f", "7a2f9c52d9c044cc53dd8212ed50f9d0534d943cc12f9162553d4b5bd3d45dc3", "a172358516aa770d924a4db441b15b160d03a7ca401539f2addd3eb489a7ae7f", "e3831bda05f6868525e47770a5b47e6fe898653d6697b744985b732af91dc8c7"),
}


def test_repro_v4_e2_formal_audit_is_complete_and_consistent() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    source = audit["source"]
    assert source["execution_git_sha"] == "c0d16d3ed8e3912c9350ac1bd16bf5c99b2e43b5"
    assert source["merged_main_git_sha"] == "365f835fdde7f25dd79fe29d7581ca5c16b5339d"
    assert source["execution_git_tree_sha"] == source["merged_main_git_tree_sha"] == "81067a1d35d1495833dca5722845eab0c937e540"
    assert source["execution_tree_equals_merged_main_tree"] is True
    assert source["tracked_modified_count_at_start"] == 0
    assert source["untracked_execution_input_count_at_start"] == 0
    assert source["working_tree_dirty"] is False

    assert audit["fingerprints"] == {
        "scientific_config_sha256": "f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3",
        "family_config_sha256": "983776a19e0a12937bc8a185b0fe5fdf76877d266445dcfce5f252d397a6ca8c",
        "family_component_sha256": "92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e",
        "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
    }
    assert audit["environment"]["pyomo_interface"] == "gurobi_direct"
    assert audit["environment"]["threads"] == 1
    assert audit["environment"]["highs_fallback"] is False

    design = audit["design"]
    assert design["tier_id"] == "V2"
    assert design["formal_seeds"] == list(range(2026072401, 2026072411))
    assert design["budget_indices"] == [0, 1, 2]
    assert design["budgets"] == EXPECTED_BUDGETS
    assert design["policies"] == EXPECTED_POLICIES

    expected_plan_digests = {}
    expected_plan_count = 0
    for seed in design["formal_seeds"]:
        run_id = f"formal_e2_repro_v4_v2_{seed}"
        plan_ids = sorted(
            f"E2_V2_{seed}_b{budget_index:02d}_{policy}"
            for budget_index in design["budget_indices"]
            for policy in EXPECTED_POLICIES
        )
        expected_plan_count += len(plan_ids)
        canonical = json.dumps(
            plan_ids,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expected_plan_digests[run_id] = hashlib.sha256(canonical).hexdigest()
    assert expected_plan_count == 180
    assert audit["plan_identity_sha256_by_run"] == expected_plan_digests

    runs = {run["run_id"]: run for run in audit["runs"]}
    assert set(runs) == set(EXPECTED_RUNS)
    for run_id, expected in EXPECTED_RUNS.items():
        seed, result_hash, manifest_hash, status_hash, worker_map_hash = expected
        run = runs[run_id]
        assert run["tier_id"] == "V2"
        assert run["seed"] == seed
        assert run["execution_mode"] == "formal"
        assert run["status"] == "optimal"
        assert run["planned_work_units"] == run["completed_work_units"] == 18
        assert run["parent_run_id"] == ""
        assert run["result_sha256"] == result_hash
        assert run["manifest_sha256"] == manifest_hash
        assert run["status_summary_sha256"] == status_hash
        assert run["worker_hash_map_sha256"] == worker_map_hash
        assert run["wall_seconds"] > 0.0

    counts = audit["counts"]
    assert len(runs) == counts["primary_run_count"] == 10
    work_units = sum(run["planned_work_units"] for run in runs.values())
    assert work_units == counts["planned_work_unit_count"] == 180
    assert counts["completed_work_unit_count"] == 180
    assert Counter(audit["design"]["policies"]) == Counter(
        audit["policy_summary"].keys()
    )
    assert all(row["count"] == 30 for row in audit["policy_summary"].values())
    assert 10 * 3 * 6 == work_units
    assert work_units * 100 == counts["exact_training_scenario_evaluation_count"] == 18000
    for field in (
        "infeasible_scenario_count",
        "solver_failure_count",
        "failed_primary_run_count",
        "duplicate_primary_run_count",
        "parent_run_count",
        "diagnostic_attempt_count",
    ):
        assert counts[field] == 0

    gate = audit["structural_gate"]
    assert gate["comparison_group_count"] == 10 * 3 == 30
    assert gate["endogenous_plan_count"] == 30
    assert gate["endogenous_nonzero_reserve_count"] == 0
    assert gate["max_abs_endogenous_reserve"] == 0.0
    assert gate["endogenous_zero_reserve_objective_match_count"] == 30
    assert gate["objective_match_absolute_tolerance"] == 1e-5
    assert gate["max_abs_endogenous_minus_zero_reserve_objective"] == 5.4569682106375694e-12
    assert (
        gate["max_abs_endogenous_minus_zero_reserve_objective"]
        <= gate["objective_match_absolute_tolerance"]
    )
    assert gate["max_endogenous_minus_best_positive_fixed_reserve_objective"] == -513.8054557105679
    assert gate["min_endogenous_minus_best_positive_fixed_reserve_objective"] == -1149.5801370952558
    assert gate["all_endogenous_objectives_not_worse_than_best_positive_fixed_reserve"] is True

    assert all(audit["artifact_validation"].values())
    assert audit["global_artifacts"] == {
        "family_run_registry_sha256": "5719cbe6cbec7392ac0d6d833ec4417fb9b9eb43a1357b4186f51d5a03bed8d6",
        "algorithm_performance_sha256": "2486b070ee569bcc938cdb2468eb173d658353fd181c286bdaccf6216cb791c3",
        "pilot_projection_sha256": "c3b9c26e69a46aa89a99d7b6f40ff307c308c2782405e884154bc21c906faff2",
    }
    assert audit["authorization_after_batch"] == {
        "projection_status": "passed",
        "compute_gate_passed": True,
        "formal_execution_authorized": True,
    }
    assert all(value is False for value in audit["stop_boundary"].values())
