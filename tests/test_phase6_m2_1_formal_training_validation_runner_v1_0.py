import copy
import json
from pathlib import Path

import pytest
import yaml

import src.phase6_m2_1_formal_training_validation as runner
from src.phase6_m2_development import DevelopmentStageError


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / runner.CONFIG_PATH
RUNNER = ROOT / runner.RUNNER_CONFIG_PATH
APPROVAL = ROOT / runner.APPROVAL_PATH


def _approval():
    return yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))


def test_frozen_formal_matrix_and_phase_boundary_are_exact():
    config = runner.load_formal_config(CONFIG)
    design = runner.load_m2_1_config(ROOT / runner.DESIGN_CONFIG_PATH)
    cases = runner.build_formal_cases(config, design)
    assert len(cases) == 10
    assert [case.triplet_position for case in cases] == list(range(1, 11))
    assert [case.training_seed for case in cases] == list(range(2026090101, 2026090111))
    assert [case.validation_seed for case in cases] == list(range(2026090201, 2026090211))
    assert [case.test_seed for case in cases] == list(range(2026090301, 2026090311))
    assert all(case.includes_test_probe is False for case in cases)
    assert config["formal_matrix"]["validation_candidate_plan_count"] == 30
    assert config["formal_matrix"]["validation_exact_recourse_evaluation_count"] == 60000
    assert config["formal_matrix"]["test_scenario_generation_count"] == 0
    assert config["formal_matrix"]["test_recourse_evaluation_count"] == 0
    assert config["execution_boundaries"]["selected_plan_freeze_authorized"] is False
    assert config["execution_boundaries"]["formal_test_authorized"] is False


def test_approval_matches_current_fingerprints_and_does_not_authorize_test():
    approval = _approval()
    actual = runner.formal_fingerprints(ROOT, CONFIG, RUNNER)
    for field in (
        "scientific_config_sha256",
        "e3_component_sha256",
        "family_component_sha256",
        "runner_config_sha256",
    ):
        assert approval["approved_fingerprints"][field] == actual[field]
    assert len(actual["environment_sha256"]) == 64
    int(actual["environment_sha256"], 16)
    assert approval["approved_fingerprints"]["environment_sha256"] == (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    )
    assert approval["formal_training_authorized"] is True
    assert approval["formal_validation_authorized"] is True
    assert approval["selected_plan_freeze_authorized"] is False
    assert approval["formal_test_authorized"] is False
    assert approval["formal_extension_authorized"] is False
    assert all(value == 0 for value in approval["execution_counts_in_this_revision"].values())


def test_reviewed_pr67_evidence_is_cryptographically_cross_bound(tmp_path):
    config = runner.load_formal_config(CONFIG)
    approval = _approval()
    parent = config["reviewed_pilot_evidence"]
    for relative in (parent["audit_path"], parent["registry_path"], parent["projection_path"]):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
    audit = json.loads((ROOT / parent["audit_path"]).read_text(encoding="utf-8"))
    (tmp_path / parent["registry_path"]).write_text("reviewed-registry", encoding="utf-8")
    projection = {
        "fingerprints": audit["fingerprints"], "pilot_compute_gate_passed": True,
        "formal_extension_authorized": False,
    }
    (tmp_path / parent["projection_path"]).write_text(json.dumps(projection), encoding="utf-8")
    local = copy.deepcopy(config)
    local_parent = local["reviewed_pilot_evidence"]
    local_parent["registry_sha256"] = runner.sha256_file(tmp_path / parent["registry_path"])
    local_parent["projection_sha256"] = runner.sha256_file(tmp_path / parent["projection_path"])
    audit["global_artifacts"] = {
        "pilot_run_registry_sha256": local_parent["registry_sha256"],
        "pilot_projection_sha256": local_parent["projection_sha256"],
    }
    (tmp_path / parent["audit_path"]).write_text(json.dumps(audit), encoding="utf-8")
    local_parent["audit_sha256"] = runner.sha256_file(tmp_path / parent["audit_path"])
    local_approval = dict(approval)
    local_approval["reviewed_pilot_audit_sha256"] = local_parent["audit_sha256"]
    local_approval["reviewed_pilot_registry_sha256"] = local_parent["registry_sha256"]
    local_approval["reviewed_pilot_projection_sha256"] = local_parent["projection_sha256"]
    evidence = runner._validate_reviewed_pilot(tmp_path, local, local_approval)
    assert evidence["audit"]["projection"]["pilot_compute_gate_passed"] is True
    local_approval["reviewed_pilot_registry_sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="not bound"):
        runner._validate_reviewed_pilot(tmp_path, local, local_approval)


def test_explicit_authorization_is_required_before_execution_preflight(monkeypatch):
    approval = _approval()
    monkeypatch.setattr(runner, "formal_fingerprints", lambda *args: approval["approved_fingerprints"])
    monkeypatch.setattr(runner, "_validate_reviewed_pilot", lambda *args: {"reviewed": True})
    monkeypatch.setattr(runner, "validate_execution_source", lambda *args, **kwargs: {"commit_sha": "a", "tree_sha": "b"})
    monkeypatch.setattr(runner, "validate_locked_environment", lambda *args: {"python": "3.12.10"})
    monkeypatch.setattr(runner, "capture_runtime_context", lambda **kwargs: {
        "solver": {"selected": "gurobi_direct", "version": "13.0.2", "threads": 1},
    })
    with pytest.raises(PermissionError, match="authorize-formal"):
        runner.validate_preflight(
            root=ROOT, config_path=CONFIG, runner_path=RUNNER,
            approval_path=APPROVAL, authorize=False,
        )
    observed = runner.validate_preflight(
        root=ROOT, config_path=CONFIG, runner_path=RUNNER,
        approval_path=APPROVAL, authorize=True,
    )
    assert observed["reviewed_pilot"] == {"reviewed": True}


def test_primary_cannot_select_cases_and_failure_stops_batch(tmp_path, monkeypatch):
    config = runner.load_formal_config(CONFIG)
    design = runner.load_m2_1_config(ROOT / runner.DESIGN_CONFIG_PATH)
    preflight = {
        "config": config, "design": design,
        "runner": yaml.safe_load(RUNNER.read_text(encoding="utf-8")),
        "fingerprints": _approval()["approved_fingerprints"],
        "locked_environment": {}, "source": {"commit_sha": "a", "tree_sha": "b"},
    }
    monkeypatch.setattr(runner, "OUTPUT_ROOT", "outputs/test-formal")
    monkeypatch.setattr(runner, "validate_preflight", lambda **kwargs: preflight)
    with pytest.raises(ValueError, match="all ten"):
        runner.run_formal_training_validation(
            root=tmp_path, config_path=CONFIG, runner_path=RUNNER, approval_path=APPROVAL,
            authorize=True, run_id_prefix="formal", case_ids=[runner.build_formal_cases(config, design)[0].case_id],
        )
    calls = []
    def fake_case(**kwargs):
        calls.append(kwargs["case"].case_id)
        status = "optimal" if len(calls) == 1 else "timeout"
        return {"status": status, "projection": {"formal_training_validation_gate_passed": False}}
    monkeypatch.setattr(runner, "run_case", fake_case)
    results = runner.run_formal_training_validation(
        root=tmp_path, config_path=CONFIG, runner_path=RUNNER, approval_path=APPROVAL,
        authorize=True, run_id_prefix="formal",
    )
    assert len(results) == len(calls) == 2
    assert results[-1]["status"] == "timeout"


def test_projection_recomputes_all_ten_runs_and_never_authorizes_test(tmp_path, monkeypatch):
    config = runner.load_formal_config(CONFIG)
    design = runner.load_m2_1_config(ROOT / runner.DESIGN_CONFIG_PATH)
    cases = runner.build_formal_cases(config, design)
    fingerprints = _approval()["approved_fingerprints"]
    rows = []
    results = {}
    for case in cases:
        run_id = f"formal_{case.case_id}"
        rows.append({
            "run_id": run_id, "parent_run_id": "", "case_id": case.case_id,
            "status": "optimal", **fingerprints,
        })
        results[run_id] = {
            "run_id": run_id, "case_id": case.case_id, "case": case.as_dict(),
            "status": "optimal", "science": {"first_stage_plan_artifacts": {
                    candidate: {
                        "strategy_id": candidate,
                        "finalized_plan_artifact_sha256": (candidate[0] * 64),
                        "regular_purchase_sha256": (candidate[-1] * 64),
                        "reserve_amount": 1.0,
                        "exact_training_objective": 2.0,
                        "training_joint_scenario_set_sha256": "a" * 64,
                    }
                for candidate in runner.CANDIDATE_IDS
            }},
        }
    monkeypatch.setattr(runner, "_read_registry", lambda path: rows)
    monkeypatch.setattr(runner, "_validate_artifact", lambda output, row: results[row["run_id"]])
    monkeypatch.setattr(runner, "_validate_plan", lambda *args: None)
    monkeypatch.setattr(runner, "_derive_triplet", lambda science, case: {
        "selected_candidate_id": "minimum_endpoint",
        "validation_plan_count": 3,
        "validation_recourse_evaluation_count": 6000,
    })
    projection = runner.update_projection(
        output_root=tmp_path, config=config, design=design, fingerprints=fingerprints,
    )
    assert projection["verified_primary_run_count"] == 10
    assert projection["validation_candidate_plan_count"] == 30
    assert projection["validation_exact_recourse_evaluation_count"] == 60000
    assert projection["formal_training_validation_gate_passed"] is True
    assert projection["selected_plan_freeze_authorized"] is False
    assert projection["formal_test_authorized"] is False
    assert projection["formal_extension_authorized"] is False
    rows[0]["status"] = "timeout"
    results[rows[0]["run_id"]]["status"] = "timeout"
    blocked = runner.update_projection(
        output_root=tmp_path, config=config, design=design, fingerprints=fingerprints,
    )
    assert blocked["formal_training_validation_gate_passed"] is False
    assert blocked["failed_primary_run_ids"] == [rows[0]["run_id"]]


@pytest.mark.parametrize("native", ["time_limit", "master_time_limit"])
def test_native_solver_timeout_is_an_immutable_timeout(tmp_path, monkeypatch, native):
    config = runner.load_formal_config(CONFIG)
    design = runner.load_m2_1_config(ROOT / runner.DESIGN_CONFIG_PATH)
    case = runner.build_formal_cases(config, design)[0]
    monkeypatch.setattr(runner, "capture_runtime_context", lambda **kwargs: {})
    monkeypatch.setattr(runner, "update_projection", lambda **kwargs: {"formal_training_validation_gate_passed": False})
    def timeout_executor(**kwargs):
        raise DevelopmentStageError("complete_extensive_optimum", native, "solver stopped")
    result = runner.run_case(
        root=tmp_path, output_root=tmp_path / "out",
        matrix_path=ROOT / "configs/phase6_experiment_matrix.yaml",
        config=config, design=design, runner=yaml.safe_load(RUNNER.read_text(encoding="utf-8")),
        fingerprints=_approval()["approved_fingerprints"], locked_environment={},
        source={"commit_sha": "a", "tree_sha": "b"}, case=case,
        run_id=f"timeout_{native}", science_executor=timeout_executor,
    )
    assert result["status"] == "timeout"
    assert result["failure"]["solver_status"] == native


def test_status_reader_rejects_unsafe_run_id(tmp_path):
    from src.phase6_m2_1_formal_training_validation_status import read_status
    with pytest.raises(ValueError):
        read_status(tmp_path, "../escape")


def test_formal_test_payload_is_rejected_and_not_authorized(tmp_path, monkeypatch):
    config = runner.load_formal_config(CONFIG)
    design = runner.load_m2_1_config(ROOT / runner.DESIGN_CONFIG_PATH)
    case = runner.build_formal_cases(config, design)[0]
    monkeypatch.setattr(runner, "capture_runtime_context", lambda **kwargs: {})
    monkeypatch.setattr(runner, "update_projection", lambda **kwargs: {
        "formal_training_validation_gate_passed": False,
        "formal_test_authorized": False,
    })
    result = runner.run_case(
        root=tmp_path, output_root=tmp_path / "out",
        matrix_path=ROOT / "configs/phase6_experiment_matrix.yaml",
        config=config, design=design, runner=yaml.safe_load(RUNNER.read_text(encoding="utf-8")),
        fingerprints=_approval()["approved_fingerprints"], locked_environment={},
        source={"commit_sha": "a", "tree_sha": "b"}, case=case,
        run_id="forbidden_test_payload",
        science_executor=lambda **kwargs: {"test_results": {"forbidden": True}, "test_scenario_count": 2000},
    )
    assert result["status"] == "stage_failure"
    assert "test data" in result["failure"]["message"]
    assert result["projection"]["formal_test_authorized"] is False


def test_registry_finalization_failure_leaves_bounded_terminal_diagnostic(tmp_path, monkeypatch):
    config = runner.load_formal_config(CONFIG)
    design = runner.load_m2_1_config(ROOT / runner.DESIGN_CONFIG_PATH)
    case = runner.build_formal_cases(config, design)[0]
    monkeypatch.setattr(runner, "capture_runtime_context", lambda **kwargs: {})
    monkeypatch.setattr(runner, "_write_registry", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("locked")))
    with pytest.raises(OSError, match="locked"):
        runner.run_case(
            root=tmp_path, output_root=tmp_path / "out",
            matrix_path=ROOT / "configs/phase6_experiment_matrix.yaml",
            config=config, design=design, runner=yaml.safe_load(RUNNER.read_text(encoding="utf-8")),
            fingerprints=_approval()["approved_fingerprints"], locked_environment={},
            source={"commit_sha": "a", "tree_sha": "b"}, case=case,
            run_id="registry_failure",
            science_executor=lambda **kwargs: {"test_results": {}, "test_scenario_count": 0},
        )
    diagnostic = json.loads((
        tmp_path / "out/training_validation/runs/registry_failure/runner_exception.json"
    ).read_text(encoding="utf-8"))
    assert diagnostic["status"] == "runner_exception"
    assert diagnostic["stage"] == "registry_finalization"
    assert len(json.dumps(diagnostic).encode("utf-8")) <= 16384
