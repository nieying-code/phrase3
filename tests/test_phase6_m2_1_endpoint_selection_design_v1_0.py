from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import pytest
import yaml

from src import phase6_m2_1_endpoint_selection as m21
from src import run_phase6_m2_1_endpoint_selection as cli


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / m21.CONFIG_PATH
RUNNER = ROOT / m21.RUNNER_PATH
APPROVAL = ROOT / m21.APPROVAL_PATH
AUDIT = ROOT / "docs/handoffs/2026-08-21_phase6_m2_1_endpoint_selection_design_v1_0_audit.json"
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": "6ae0e6623647f9d70bf7a6cdba6114585a1a4b72727cdd222025508b68829941",
    "e3_component_sha256": "9697e08863336c3c4917eaabd5a9e7f32145d4cbfba57a78f04b51143883d279",
    "family_component_sha256": "b9046cb7447612cc2c33d43f8e788d54130ef2bdc75f90005c4123979c32ed8f",
    "runner_config_sha256": "aeb4281753a938e61d03c4c537a126fb7d752e7df63620f1788f01f6b304fc62",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_parent_evidence_and_design_artifacts_are_byte_locked() -> None:
    config = m21.load_m2_1_config(CONFIG)
    assert m21.validate_parent_evidence(ROOT) == {
        identity: expected for identity, (_, expected) in m21.PARENT_AUDITS.items()
    }
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["base"] == {
        "pr61_merge_commit": "e03c6fcbe15e8b25ef73e7b760bc31ca29219e27",
        "pr61_merge_tree": "e5d131c47f3f70dc8230810440862d3aae02e305",
        "branch": "agent/phase6-m2-1-endpoint-selection-design",
    }
    expected_artifacts = {
        "config": (CONFIG, "75668fa7a4759d02f4325113aa5abd9ffaa0e1031ea435ef43fc130297700e5c"),
        "runner_config": (RUNNER, "aeb4281753a938e61d03c4c537a126fb7d752e7df63620f1788f01f6b304fc62"),
        "approval": (APPROVAL, "8ec9f6b935e092256636d20f28689889355817f7f0c3650975614cc3a104b824"),
        "protocol_module": (ROOT / "src/phase6_m2_1_endpoint_selection.py", "b9f1ce9e450ac5e420a5eb8ef775ed57a016ff44285f349ae63afaf71e0d52cf"),
        "cli_guard": (ROOT / "src/run_phase6_m2_1_endpoint_selection.py", "f5389de11078bc21ea8f3484958a7f8df8b7d02c813b9fef8cddb04c5cff88bd"),
    }
    assert audit["artifact_sha256"] == {
        name: expected for name, (_, expected) in expected_artifacts.items()
    }
    for path, expected in expected_artifacts.values():
        assert sha256(path) == expected
    assert config["parent_evidence"]["existing_M2_results_are_read_only"] is True


def test_fingerprints_are_independent_and_approval_is_non_executable() -> None:
    actual = m21.m2_1_fingerprints(ROOT, CONFIG, RUNNER)
    for field in EXPECTED_FINGERPRINTS:
        if field != "environment_sha256":
            assert actual[field] == EXPECTED_FINGERPRINTS[field]
    assert len(actual["environment_sha256"]) == 64
    int(actual["environment_sha256"], 16)
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    assert approval["approved_fingerprints"] == EXPECTED_FINGERPRINTS
    assert approval["status"] == "design_review_pending"
    assert approval["accept_M2_authorization"] is False
    for field in (
        "pilot_authorized", "formal_training_authorized", "formal_validation_authorized",
        "selected_plan_freeze_authorized", "formal_test_authorized",
    ):
        assert approval[field] is False


def test_new_seed_sets_are_exact_disjoint_and_not_in_prior_tracks() -> None:
    config = m21.load_m2_1_config(CONFIG)
    observed = m21._seed_sets(config)
    assert observed == {
        "pilot_training_seeds": (2026090401, 2026090402, 2026090403),
        "pilot_validation_seeds": (2026090501, 2026090502, 2026090503),
        "pilot_test_seeds": (2026090701, 2026090702, 2026090703),
        "formal_training_seeds": tuple(range(2026090101, 2026090111)),
        "formal_validation_seeds": tuple(range(2026090201, 2026090211)),
        "formal_test_seeds": tuple(range(2026090301, 2026090311)),
    }
    all_new = set().union(*(set(values) for values in observed.values()))
    assert sum(map(len, observed.values())) == len(all_new) == 39
    prior_numbers: set[int] = set()
    derived_pilot = ROOT / "configs/phase6_m2_1_pilot.yaml"
    for path in (ROOT / "configs").glob("phase6*.yaml"):
        # The reviewed runner protocol must repeat the frozen M2.1 seeds by
        # identity; it is not an independent seed source or a prior track.
        if path in {CONFIG, derived_pilot}:
            continue
        text = path.read_text(encoding="utf-8")
        for token in text.replace("[", " ").replace("]", " ").replace(",", " ").split():
            value = token.rstrip(":")
            if value.isdigit() and len(value) == 10 and value.startswith("2026"):
                prior_numbers.add(int(value))
    assert all_new.isdisjoint(prior_numbers)


def test_preregistered_plan_counts_and_single_primary_estimand() -> None:
    config = m21.load_m2_1_config(CONFIG)
    pilot = m21.build_preregistered_plan(config, "pilot")
    formal = m21.build_preregistered_plan(config, "formal")
    assert pilot["training_interval_runs"] == 3
    assert pilot["validation_candidate_plans"] == 9
    assert pilot["validation_exact_recourse_evaluations"] == 18000
    assert pilot["test_strategy_plans"] == 6
    assert pilot["test_exact_recourse_evaluations"] == 12000
    assert formal["training_interval_runs"] == 10
    assert formal["validation_candidate_plans"] == 30
    assert formal["validation_exact_recourse_evaluations"] == 60000
    assert formal["test_strategy_plans"] == 60
    assert formal["test_exact_recourse_evaluations"] == 120000
    statistics = config["statistical_protocol"]
    assert statistics["primary_confirmatory_test_count"] == 1
    assert config["formal_comparison"]["primary_estimand"] == "M2_1_minus_M2_oos_cvar95"
    assert statistics["multiple_testing_adjustment"] == "not_applicable_one_primary_test"


def test_three_candidate_reserves_and_validation_only_lexicographic_selection() -> None:
    assert m21.reserve_candidates(10.0, 30.0) == {
        "minimum_endpoint": 10.0,
        "interval_midpoint": 20.0,
        "maximum_endpoint": 30.0,
    }
    with pytest.raises(m21.M21ProtocolError):
        m21.reserve_candidates(30.0, 10.0)
    metrics = {
        "minimum_endpoint": {"total_cost_cvar95": 100.0, "mean_total_cost": 90.0, "reserve": 10.0},
        "interval_midpoint": {"total_cost_cvar95": 99.0, "mean_total_cost": 92.0, "reserve": 20.0},
        "maximum_endpoint": {"total_cost_cvar95": 99.0, "mean_total_cost": 91.0, "reserve": 30.0},
    }
    selected = m21.select_validation_candidate(metrics)
    assert selected["selected_candidate_id"] == "maximum_endpoint"
    assert selected["test_metrics_used"] is False
    tied = {
        "minimum_endpoint": {"total_cost_cvar95": 100.0, "mean_total_cost": 90.0, "reserve": 10.0},
        "interval_midpoint": {"total_cost_cvar95": 100.0, "mean_total_cost": 90.0, "reserve": 20.0},
        "maximum_endpoint": {"total_cost_cvar95": 100.0, "mean_total_cost": 90.0, "reserve": 30.0},
    }
    assert m21.select_validation_candidate(tied)["selected_candidate_id"] == "minimum_endpoint"
    for illegal in (math.nan, math.inf, -1.0):
        tampered = {name: dict(row) for name, row in tied.items()}
        tampered["minimum_endpoint"]["total_cost_cvar95"] = illegal
        with pytest.raises(m21.M21ProtocolError):
            m21.select_validation_candidate(tampered)


def _scenario_identity(fill: str) -> dict[str, str]:
    return {field: fill * 64 for field in m21.SCENARIO_IDENTITY_FIELDS}


def _plan_identity(fill: str = "a") -> dict[str, object]:
    return {
        "finalized_plan_artifact_sha256": fill * 64,
        "regular_purchase_sha256": "b" * 64,
        "reserve_amount": 100.0,
        "exact_training_objective": 1000.0,
        "training_joint_scenario_set_sha256": "c" * 64,
    }


def test_validation_and_test_alternatives_share_one_scenario_identity() -> None:
    identity = _scenario_identity("a")
    validation = {candidate: dict(identity) for candidate in m21.CANDIDATE_IDS}
    test = {strategy: dict(identity) for strategy in m21.TEST_STRATEGIES}
    assert m21.validate_shared_scenario_identity(
        validation, expected_ids=m21.CANDIDATE_IDS, phase="validation"
    ) == identity
    assert m21.validate_shared_scenario_identity(
        test, expected_ids=m21.TEST_STRATEGIES, phase="test"
    ) == identity
    for field in m21.SCENARIO_IDENTITY_FIELDS:
        tampered = {name: dict(row) for name, row in validation.items()}
        tampered["interval_midpoint"][field] = "d" * 64
        with pytest.raises(m21.M21ProtocolError, match="common_random_number_mismatch"):
            m21.validate_shared_scenario_identity(
                tampered, expected_ids=m21.CANDIDATE_IDS, phase="validation"
            )
        tampered_test = {name: dict(row) for name, row in test.items()}
        tampered_test["fixed_autonomous_reserve_0_50"][field] = "e" * 64
        with pytest.raises(m21.M21ProtocolError, match="common_random_number_mismatch"):
            m21.validate_shared_scenario_identity(
                tampered_test, expected_ids=m21.TEST_STRATEGIES, phase="test"
            )


def test_minimum_endpoint_is_the_unique_M2_control_plan() -> None:
    identity = _plan_identity()
    assert m21.validate_minimum_endpoint_control_binding(
        identity, dict(identity), selected_candidate_id="minimum_endpoint",
        selected_plan=dict(identity),
    ) == identity
    m21.validate_selected_minimum_test_difference(
        selected_candidate_id="minimum_endpoint", paired_difference=0.0, tolerance=1.0e-8,
    )
    for field in m21.PLAN_IDENTITY_FIELDS:
        tampered = dict(identity)
        tampered[field] = 101.0 if field in {"reserve_amount", "exact_training_objective"} else "d" * 64
        with pytest.raises(m21.M21ProtocolError, match="identity mismatch"):
            m21.validate_minimum_endpoint_control_binding(identity, tampered)
    with pytest.raises(m21.M21ProtocolError, match="must reuse"):
        m21.validate_minimum_endpoint_control_binding(
            identity, dict(identity), selected_candidate_id="minimum_endpoint",
            selected_plan=_plan_identity("d"),
        )
    with pytest.raises(m21.M21ProtocolError, match="differs"):
        m21.validate_selected_minimum_test_difference(
            selected_candidate_id="minimum_endpoint", paired_difference=1.0e-5,
            tolerance=1.0e-8,
        )


def test_config_tampering_is_rejected(tmp_path: Path) -> None:
    payload = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    mutations = (
        lambda row: row["scientific_scope"].__setitem__("beta", 1.3),
        lambda row: row["candidate_protocol"].__setitem__("candidate_ids", ["minimum_endpoint"]),
        lambda row: row["candidate_protocol"]["minimum_endpoint_identity_binding"].__setitem__("generated_and_finalized_once", False),
        lambda row: row["validation_selection"].__setitem__("criterion_order", ["minimum_mean_total_cost"]),
        lambda row: row["validation_selection"].__setitem__("test_data_use_for_selection_forbidden", False),
        lambda row: row["validation_selection"]["common_random_numbers"].__setitem__("candidate_specific_random_draws_allowed", 1),
        lambda row: row["formal_comparison"].__setitem__("primary_estimand", "posthoc_metric"),
        lambda row: row["formal_comparison"]["common_random_numbers"].__setitem__("all_six_strategies_reference_same_finalized_scenario_artifact", False),
        lambda row: row["execution_boundaries"].__setitem__("pilot_authorized", True),
    )
    for index, mutate in enumerate(mutations):
        changed = deepcopy(payload)
        mutate(changed)
        path = tmp_path / f"changed_{index}.yaml"
        path.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")
        with pytest.raises(m21.M21ProtocolError):
            m21.load_m2_1_config(path)


def test_design_cli_cannot_generate_scenarios_or_call_gurobi(monkeypatch, capsys) -> None:
    monkeypatch.setattr(m21, "validate_execution_source", lambda *args, **kwargs: {})
    # CI hosts are not the approved experiment machine.  Preserve the real
    # preflight's strict environment check while injecting the reviewed
    # experiment identity for this cross-platform authorization test.
    monkeypatch.setattr(
        m21,
        "m2_1_fingerprints",
        lambda *args, **kwargs: dict(EXPECTED_FINGERPRINTS),
    )
    with pytest.raises(m21.M21ExecutionNotAuthorized):
        m21.validate_design_only_preflight(
            root=ROOT, config_path=CONFIG, runner_path=RUNNER, approval_path=APPROVAL,
            authorize_pilot=True,
        )
    monkeypatch.setattr(
        cli,
        "validate_design_only_preflight",
        lambda **kwargs: (_ for _ in ()).throw(
            m21.M21ExecutionNotAuthorized("design-only guard")
        ),
    )
    assert cli.main(["--authorize-pilot-execution"]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "execution_not_authorized"
    assert output["scenario_generation_count"] == 0
    assert output["gurobi_call_count"] == 0
    source = (ROOT / "src/run_phase6_m2_1_endpoint_selection.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert calls.isdisjoint({"generate_phase6_data", "generate_m2_data", "SolverFactory"})


def test_audit_records_zero_execution_and_no_authorization() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["fingerprints"] == EXPECTED_FINGERPRINTS
    assert audit["status"] == "candidate_design_ready_for_review"
    assert audit["design"]["test_data_used_for_selection"] is False
    assert audit["design"]["primary_confirmatory_test_count"] == 1
    assert audit["design"]["validation_candidates_share_one_scenario_identity_per_triplet"] is True
    assert audit["design"]["test_strategies_share_one_scenario_identity_per_triplet"] is True
    assert audit["design"]["scenario_identity_field_count"] == 7
    assert audit["design"]["minimum_endpoint_is_unique_M2_control_artifact"] is True
    assert audit["design"]["minimum_endpoint_plan_identity_field_count"] == 5
    assert audit["design"]["selected_minimum_endpoint_reuses_M2_control_artifact"] is True
    assert audit["CI"] == "recorded_in_pr_body"
    assert audit["execution_boundaries"] == {
        "scientific_runner_enabled": False,
        "pilot_authorized": False,
        "formal_training_authorized": False,
        "formal_validation_authorized": False,
        "selected_plan_freeze_authorized": False,
        "formal_test_authorized": False,
        "M2_1_runs": 0,
        "scenario_generation_count": 0,
        "gurobi_call_count": 0,
        "algorithm_performance_runs": 0,
        "M0_E3_runs": 0,
    }
