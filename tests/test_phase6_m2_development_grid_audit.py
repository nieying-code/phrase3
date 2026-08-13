import itertools
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-13_phase6_m2_development_grid_audit.json"

SEEDS = (2026081201, 2026081202, 2026081203)
BETAS = (0.9, 1.1, 1.3)
PROFILES = ("C0", "C1", "C2")
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": "9c552774ade43ceaa906b2e24fa2559a802108fa42a7ff65ca70977f054e8e48",
    "e3_component_sha256": "3d3b29d6dba5b191a5cc8c2f660c789bafcf33cc192e4b45f34724aca0336cf5",
    "family_component_sha256": "455cd02cf8afbc6ce9e93a222cd320182da1ea37f65f0ea7962f4496820cd87a",
    "runner_config_sha256": "83a045e44149e7a899a3549c6f3d49a0a002e3230841efbaace7edef1034ae8c",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}


def _case_id(seed: int, beta: float, profile: str) -> str:
    return f"V1_seed{seed}_beta{beta:.2f}_profile{profile}".replace(".", "p")


def test_m2_development_grid_rebuilds_run_and_gate_evidence() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["results_evidence_commit"] == "98fabff"
    assert audit["ci_validated_audit_head"] == "eace428"
    assert audit["draft_pr"] == "https://github.com/nieying-code/phrase3/pull/45"
    assert audit["execution"]["git_sha"] == "2cdb09bd887bc8887ab956a0a0281d7c30170a40"
    assert audit["execution"]["git_tree_sha"] == "8a3a6865e56b8214160ac97e0958041025a89ee0"
    assert audit["execution"]["working_tree_dirty"] is False
    assert audit["execution"]["untracked_execution_input_count_at_start"] == 0
    assert audit["fingerprints"] == EXPECTED_FINGERPRINTS
    assert audit["mapping_hashes"] == {
        "run_artifact_mapping_sha256": "5e8dedaf26113bf1602bcf9813265a77990b734540e25a2bef314a9940b6275a",
        "science_evidence_mapping_sha256": "619c40b858ca32728f33b2cccb32df150ef957307ab9d62840ab0037f285c4b0",
    }
    assert audit["global_artifacts"] == {
        "registry_sha256": "e54f662fce95b966944eb712678e781c1dd59e534c889efaf693b5aa7049d61a",
        "projection_sha256": "7128c3673ba58255b5dbff805f22a50d674cf637f043dda22bb7de230a5376b8",
    }

    runs = audit["runs"]
    expected = {
        _case_id(seed, beta, profile): (seed, beta, profile)
        for seed, beta, profile in itertools.product(SEEDS, BETAS, PROFILES)
    }
    assert len(runs) == 27
    assert {row["case_id"] for row in runs} == set(expected)
    assert len({row["run_id"] for row in runs}) == 27
    for row in runs:
        seed, beta, profile = expected[row["case_id"]]
        assert (row["seed"], row["beta"], row["profile_id"]) == (seed, beta, profile)
        assert row["run_id"] == f"m2dev_v1_1_20260813_{row['case_id']}"
        assert row["status"] == "optimal" and row["parent_run_id"] is None
        assert row["fingerprints"] == EXPECTED_FINGERPRINTS
        assert row["git_sha"] == audit["execution"]["git_sha"]
        assert row["git_tree_sha"] == audit["execution"]["git_tree_sha"]
        assert row["scenario_identity_count"] == 50
        assert row["solver"] == "gurobi_direct"
        assert row["gurobi_optimizer_version"] == "13.0.2"
        assert row["gurobipy_version"] == "13.0.2" and row["threads"] == 1
        assert all(len(value) == 64 for value in row["artifacts"].values())
        assert math.isclose(row["budget"], beta * row["reference_budget"], abs_tol=1e-9)
        robust = max(0.0, row["R_min_opt"] - row["R_min_feas"])
        ratio = robust / row["budget"]
        assert math.isclose(row["R_disc_robust"], robust, abs_tol=1e-9)
        assert math.isclose(row["R_disc_robust_ratio"], ratio, abs_tol=1e-12)
        assert row["numerical_activation"] == (ratio > 1e-4)
        assert row["substantive_activation"] == (ratio >= 0.01)
        assert row["minimum_endpoint_status"] == row["maximum_endpoint_status"] == "optimal"
        assert abs(row["minimum_endpoint_consistency_difference"]) <= row["objective_tolerance"] + 1e-8
        assert abs(row["maximum_endpoint_consistency_difference"]) <= row["objective_tolerance"] + 1e-8
        assert row["endpoint_failure_counts"] == {
            "minimum": {"infeasible": 0, "solver_failure": 0, "missing": 0},
            "maximum": {"infeasible": 0, "solver_failure": 0, "missing": 0},
        }
        assert [policy["rho"] for policy in row["fixed_reserve_policies"]] == [0.0, 0.1, 0.3, 0.5]
        assert all(policy["status"] == "optimal" and policy["regular_purchase_reoptimized"] for policy in row["fixed_reserve_policies"])

    rebuilt = []
    for beta, profile in itertools.product(BETAS, PROFILES):
        members = [row for row in runs if row["beta"] == beta and row["profile_id"] == profile]
        substantive = sum(row["substantive_activation"] for row in members)
        c0 = [row for row in runs if row["beta"] == beta and row["profile_id"] == "C0"]
        gate = profile in {"C1", "C2"} and substantive >= 2 and not any(row["substantive_activation"] for row in c0)
        rebuilt.append((beta, profile, len(members), substantive, gate))
    recorded = [(row["beta"], row["profile_id"], row["optimal_seed_count"], row["substantive_activation_seed_count"], row["gate_passed"]) for row in audit["projection"]["combinations"]]
    assert recorded == rebuilt
    assert [(row["beta"], row["profile_id"]) for row in audit["projection"]["passed_combinations"]] == [(0.9, "C2"), (1.1, "C2"), (1.3, "C2")]
    assert audit["projection"]["common_random_numbers_verified"] is True
    assert audit["projection"]["development_activation_gate_passed"] is True
    assert audit["projection"]["formal_extension_authorized"] is False
    assert audit["projection"]["missing_case_ids"] == []
    assert audit["projection"]["invalid_primary_run_ids"] == []
    assert audit["projection"]["duplicate_case_ids"] == []
    assert audit["aggregate"]["optimal_run_count"] == 27
    assert audit["aggregate"]["substantive_activation_run_count"] == 9
    assert audit["aggregate"]["failure_count"] == 0
    assert set(audit["execution_boundaries"].values()) == {0, 27}
    assert audit["github_actions"] == {
        "run_id": 31662287525,
        "url": "https://github.com/nieying-code/phrase3/actions/runs/31662287525",
        "linux": "success",
        "windows": "success",
    }
