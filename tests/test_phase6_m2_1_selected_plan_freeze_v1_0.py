import hashlib
import json
from pathlib import Path

import yaml

from src.phase6_m2_1_endpoint_selection import PLAN_IDENTITY_FIELDS


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/phase6_m2_1_selected_plan_freeze_v1_0.yaml"
AUDIT = ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_selected_plan_freeze_v1_0_audit.json"
PARENT = ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_formal_training_validation_results_v1_0_audit.json"


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load():
    return (
        yaml.safe_load(CONFIG.read_text(encoding="utf-8")),
        json.loads(AUDIT.read_text(encoding="utf-8")),
        json.loads(PARENT.read_text(encoding="utf-8")),
    )


def test_parent_evidence_and_freeze_artifact_are_byte_locked():
    config, audit, parent = _load()
    assert _sha(PARENT) == config["reviewed_training_validation_evidence"]["pr69_audit_sha256"] == (
        audit["parent_evidence"]["pr69_audit_sha256"]
    )
    assert _sha(CONFIG) == audit["freeze_artifact"]["sha256"] == (
        "4438f01933a3b26ce79272b67ecb8fbb458f561bc1edb7073334ab183e1a783e"
    )
    evidence = config["reviewed_training_validation_evidence"]
    assert evidence["training_validation_registry_sha256"] == parent["global_artifacts"]["formal_training_validation_run_registry_sha256"]
    assert evidence["training_validation_projection_sha256"] == parent["global_artifacts"]["formal_training_validation_projection_sha256"]
    assert parent["projection"]["formal_training_validation_gate_passed"] is True


def test_ten_selected_plans_are_recomputed_from_reviewed_runs():
    config, audit, parent = _load()
    frozen = config["selected_plans"]
    assert len(frozen) == 10
    parent_rows = {row["case_id"]: row for row in parent["runs"]}
    assert set(parent_rows) == {row["case_id"] for row in frozen}
    for row in frozen:
        source = parent_rows[row["case_id"]]
        selected_id = source["selected_candidate_id"]
        assert row["selected_candidate_id"] == selected_id
        assert row["source_run_id"] == source["run_id"]
        assert (row["training_seed"], row["validation_seed"], row["formal_test_seed"]) == (
            source["training_seed"], source["validation_seed"], source["reserved_test_seed"]
        )
        assert row["plan_identity"] == source["candidates"][selected_id]["plan_identity"]
        assert tuple(row["plan_identity"]) == PLAN_IDENTITY_FIELDS
    assert [row["selected_candidate_id"] for row in frozen].count("minimum_endpoint") == 2
    assert [row["selected_candidate_id"] for row in frozen].count("interval_midpoint") == 0
    assert [row["selected_candidate_id"] for row in frozen].count("maximum_endpoint") == 8
    assert audit["freeze_artifact"]["selected_plan_count"] == 10


def test_selected_mapping_and_projection_order_close_independently():
    config, _, parent = _load()
    selected_mapping = {
        row["case_id"]: {field: row["plan_identity"][field] for field in PLAN_IDENTITY_FIELDS}
        for row in config["selected_plans"]
    }
    expected = "df515f14931e903902f15e2089b21a23ca27bcfca2c4162e9d74e0b3c631b831"
    assert _canonical_sha(selected_mapping) == expected
    assert parent["projection"]["selected_plan_identity_mapping_sha256"] == expected
    assert parent["projection"]["selected_candidate_ids"] == [
        row["selected_candidate_id"] for row in config["selected_plans"]
    ]


def test_formal_test_matrix_statistics_and_stop_boundary_are_frozen():
    config, audit, _ = _load()
    scope = config["scientific_scope"]
    assert scope["formal_test_triplet_count"] == 10
    assert len(scope["strategy_ids"]) == 6
    assert scope["formal_test_plan_count"] == 10 * 6 == 60
    assert scope["formal_test_exact_recourse_evaluation_count"] == 60 * 2000 == 120000
    assert scope["test_data_use_for_selection_forbidden"] is True
    stats = config["statistical_protocol"]
    assert stats["primary_estimand"] == "M2_1_minus_M2_oos_cvar95"
    assert stats["independent_unit_count"] == 10
    assert stats["bootstrap_random_seed"] == 2026090999
    assert stats["bootstrap_resamples"] == 10000
    boundaries = config["execution_boundaries"]
    assert boundaries["selected_plan_freeze_authorized"] is True
    assert boundaries["formal_test_runner_implemented"] is False
    assert boundaries["formal_test_authorized"] is False
    assert boundaries["formal_extension_authorized"] is False
    assert boundaries["next_decision"] == "permit_separate_formal_test_runner_review_PR_only"
    assert all(value == 0 for value in audit["execution_counts"].values())
