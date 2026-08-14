from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src import phase6_m2_formal_mechanism as formal
from src.phase6_m2_formal_mechanism_status import _bounded
from src.phase6_m2_formal_extension import formal_extension_fingerprints, load_formal_extension_config


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/phase6_m2_formal_extension.yaml"
PILOT_RUNNER = ROOT / "configs/phase6_m2_formal_extension_runner.yaml"
FORMAL_RUNNER = ROOT / "configs/phase6_m2_formal_mechanism_runner.yaml"
APPROVAL = ROOT / "configs/phase6_m2_formal_mechanism_approval.yaml"
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": "02d50abd609acd9d93eca6b13f6195e6eee14330e3db5c5ca75e83d2e7b56612",
    "e3_component_sha256": "87f643fd3bf90f825251641c1bdeeb25f4aebb1ea23d052913b27e0b5fdf2924",
    "family_component_sha256": "b1f9278ee8a0085e80c418f33d04c92b943c215eaf9ca2cdb6144e8dcebdb68b",
    "runner_config_sha256": "c8d9efb59649b2a3e16839cdece7c38bc5a385358c354b72310c32134f49ad8e",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}


def _preflight_payload(root: Path):
    return {
        "config": load_formal_extension_config(CONFIG),
        "fingerprints": EXPECTED_FINGERPRINTS,
        "formal_orchestrator_sha256": "a" * 64,
        "locked_environment": {},
        "source": {"commit_sha": "b" * 40, "tree_sha": "c" * 40},
    }


def test_formal_matrix_is_exactly_fifty_cases():
    config = load_formal_extension_config(CONFIG)
    cases = formal.build_formal_mechanism_cases(config)
    expected = {
        (seed, beta, profile)
        for seed in range(2026081401, 2026081411)
        for beta, profiles in ((1.1, ("C0", "C1", "T03")), (1.3, ("C0", "T03")))
        for profile in profiles
    }
    assert len(cases) == 50
    assert {(case.seed, case.beta, case.profile_id) for case in cases} == expected
    assert len({case.case_id for case in cases}) == 50
    assert all(case.run_kind == "mechanism" and case.tier_id == "M2F2" for case in cases)


def test_formal_layer_preserves_the_five_pilot_science_fingerprints():
    assert formal_extension_fingerprints(ROOT, CONFIG, PILOT_RUNNER) == EXPECTED_FINGERPRINTS
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    runner = yaml.safe_load(FORMAL_RUNNER.read_text(encoding="utf-8"))
    assert approval["approved_fingerprints"] == EXPECTED_FINGERPRINTS
    assert approval["formal_mechanism_authorized"] is True
    assert approval["formal_OOS_authorized"] is False
    assert runner["execution"]["formal_OOS_authorized"] is False
    assert approval["execution_counts_in_this_revision"] == {
        "formal_mechanism_runs": 0,
        "formal_OOS_plans": 0,
        "formal_OOS_recourse_evaluations": 0,
        "algorithm_performance_runs": 0,
        "M0_E3_runs": 0,
    }


def test_preflight_requires_explicit_formal_authorization_before_evidence_access(monkeypatch):
    touched = False

    def forbidden(*args, **kwargs):
        nonlocal touched
        touched = True
        raise AssertionError("pilot evidence must not be touched")

    monkeypatch.setattr(formal, "formal_extension_fingerprints", forbidden)
    with pytest.raises(PermissionError, match="authorize-formal-mechanism-execution"):
        formal.validate_formal_preflight(
            root=ROOT, config_path=CONFIG, runner_path=FORMAL_RUNNER,
            approval_path=APPROVAL, authorize=False,
        )
    assert touched is False


def test_primary_execution_cannot_select_cases(monkeypatch, tmp_path):
    monkeypatch.setattr(formal, "validate_formal_preflight", lambda **kwargs: _preflight_payload(tmp_path))
    with pytest.raises(ValueError, match="complete frozen 50-case batch"):
        formal.run_formal_mechanism(
            root=tmp_path, config_path=CONFIG, runner_path=FORMAL_RUNNER,
            approval_path=APPROVAL, authorize=True, run_id_prefix="formal_batch",
            case_ids=["M2F2_formal_seed2026081401_beta1p10_profileC0"],
        )


def test_primary_batch_is_strictly_serial_and_stops_on_first_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(formal, "validate_formal_preflight", lambda **kwargs: _preflight_payload(tmp_path))
    calls = []

    def fake_case(**kwargs):
        calls.append(kwargs["case"].case_id)
        return {"status": "stage_failure", "formal_progress": {"formal_OOS_authorized": False}}

    monkeypatch.setattr(formal, "run_formal_case", fake_case)
    rows = formal.run_formal_mechanism(
        root=tmp_path, config_path=CONFIG, runner_path=FORMAL_RUNNER,
        approval_path=APPROVAL, authorize=True, run_id_prefix="formal_batch",
    )
    assert len(rows) == len(calls) == 1
    assert rows[0]["status"] == "stage_failure"
    assert not (tmp_path / formal.OUTPUT_ROOT / "formal/OOS").exists()


def test_existing_formal_namespace_blocks_new_primary_batch(monkeypatch, tmp_path):
    monkeypatch.setattr(formal, "validate_formal_preflight", lambda **kwargs: _preflight_payload(tmp_path))
    base = tmp_path / formal.OUTPUT_ROOT / formal.FORMAL_SUBDIRECTORY
    base.mkdir(parents=True)
    (base / "existing-evidence.txt").write_text("immutable", encoding="utf-8")
    with pytest.raises(RuntimeError, match="empty formal namespace"):
        formal.run_formal_mechanism(
            root=tmp_path, config_path=CONFIG, runner_path=FORMAL_RUNNER,
            approval_path=APPROVAL, authorize=True, run_id_prefix="new_primary",
        )


def test_progress_gate_recomputes_all_fifty_cases_and_crn(monkeypatch, tmp_path):
    config = load_formal_extension_config(CONFIG)
    cases = formal.build_formal_mechanism_cases(config)
    fingerprints = EXPECTED_FINGERPRINTS
    orchestrator = "d" * 64
    rows = []
    results = {}
    for index, case in enumerate(cases):
        run_id = f"formal_{index:02d}"
        rows.append({
            "run_id": run_id, "parent_run_id": "", "case_id": case.case_id,
            "status": "optimal", **fingerprints,
            "formal_orchestrator_sha256": orchestrator,
        })
        results[run_id] = {
            "run_id": run_id, "case_id": case.case_id, "status": "optimal",
            "case": case.as_dict(),
            "science": {
                "first_stage_plan_artifacts": {"plan": {}},
                "scenario_component_set_sha256": {
                    "latent_draw_sha256": f"latent-{case.seed}",
                    "demand_sha256": f"demand-{case.seed}",
                    "emergency_price_sha256": f"price-{case.seed}",
                    "emergency_supply_sha256": f"supply-{case.seed}",
                    "scenario_order_sha256": f"order-{case.seed}",
                },
            },
        }
    monkeypatch.setattr(formal, "_read_registry", lambda path: rows)
    monkeypatch.setattr(formal, "_validate_artifact", lambda output_root, row, **kwargs: results[row["run_id"]])
    monkeypatch.setattr(formal, "_validate_formal_plan_artifact", lambda **kwargs: {})
    monkeypatch.setattr(formal, "_derive_mechanism", lambda science, case: {})
    monkeypatch.setattr(formal, "_finalization_failure_ids", lambda base: [])
    progress = formal.update_formal_progress(
        output_root=tmp_path, config=config, fingerprints=fingerprints,
        orchestrator_sha256=orchestrator,
    )
    assert progress["status"] == "complete"
    assert progress["completed_primary_run_count"] == 50
    assert progress["formal_mechanism_gate_passed"] is True
    assert progress["next_decision"] == "permit_mechanism_results_review_only"
    assert progress["formal_OOS_authorized"] is False
    assert all(row["verified"] for row in progress["common_random_number_checks"])


def test_failed_primary_permanently_blocks_progress_even_with_later_duplicate(monkeypatch, tmp_path):
    config = load_formal_extension_config(CONFIG)
    case = formal.build_formal_mechanism_cases(config)[0]
    rows = [
        {"run_id": "failed_primary", "parent_run_id": "", "case_id": case.case_id, "status": "stage_failure", **EXPECTED_FINGERPRINTS, "formal_orchestrator_sha256": "d" * 64},
        {"run_id": "later_primary", "parent_run_id": "", "case_id": case.case_id, "status": "optimal", **EXPECTED_FINGERPRINTS, "formal_orchestrator_sha256": "d" * 64},
    ]
    results = {
        "failed_primary": {"run_id": "failed_primary", "case_id": case.case_id, "status": "stage_failure", "case": case.as_dict(), "science": {}},
        "later_primary": {"run_id": "later_primary", "case_id": case.case_id, "status": "optimal", "case": case.as_dict(), "science": {}},
    }
    monkeypatch.setattr(formal, "_read_registry", lambda path: rows)
    monkeypatch.setattr(formal, "_validate_artifact", lambda output_root, row, **kwargs: results[row["run_id"]])
    monkeypatch.setattr(formal, "_finalization_failure_ids", lambda base: [])
    progress = formal.update_formal_progress(
        output_root=tmp_path, config=config, fingerprints=EXPECTED_FINGERPRINTS,
        orchestrator_sha256="d" * 64,
    )
    assert progress["formal_mechanism_gate_passed"] is False
    assert progress["failed_primary_run_ids"] == ["failed_primary"]
    assert progress["duplicate_case_ids"] == [case.case_id]
    assert progress["formal_OOS_authorized"] is False


def test_finalization_exception_writes_bounded_terminal_diagnostic(monkeypatch, tmp_path):
    config = load_formal_extension_config(CONFIG)
    case = formal.build_formal_mechanism_cases(config)[0]
    monkeypatch.setattr(formal, "load_phase6_matrix", lambda path: {})
    monkeypatch.setattr(formal, "capture_runtime_context", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("x" * 20000)))
    with pytest.raises(RuntimeError):
        formal.run_formal_case(
            root=ROOT, output_root=tmp_path,
            matrix_path=ROOT / "configs/phase6_experiment_matrix.yaml",
            config=config, fingerprints=EXPECTED_FINGERPRINTS,
            orchestrator_sha256="d" * 64, locked_environment={},
            source={"commit_sha": "b" * 40, "tree_sha": "c" * 40},
            case=case, run_id="formal_failure",
            science_executor=lambda **kwargs: {},
        )
    summary = json.loads((tmp_path / formal.FORMAL_SUBDIRECTORY / "runs/formal_failure/status_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "runner_exception"
    assert summary["current_stage"] == "runtime_context"
    assert len(summary["failure"]["message"]) <= 1000
    assert (tmp_path / formal.FORMAL_SUBDIRECTORY / "runs/formal_failure/status_summary.json").stat().st_size < 16384


def test_progress_status_is_small_and_informative(tmp_path):
    path = tmp_path / "formal_mechanism_progress.json"
    path.write_text(json.dumps({
        "status": "incomplete", "required_primary_run_count": 50,
        "completed_primary_run_count": 7,
        "missing_case_ids": [f"case_{index}" for index in range(43)],
        "invalid_primary_run_ids": [], "failed_primary_run_ids": [],
        "duplicate_case_ids": [], "diagnostic_run_ids": [],
        "finalization_failure_run_ids": [], "common_random_numbers_verified": False,
        "formal_mechanism_gate_passed": False,
        "next_decision": "formal_mechanism_incomplete_or_failed",
        "formal_OOS_authorized": False, "updated_at_utc": "now",
    }), encoding="utf-8")
    summary = _bounded(path)
    assert summary["required_primary_run_count"] == 50
    assert summary["completed_primary_run_count"] == 7
    assert summary["missing_case_count"] == 43
    assert summary["formal_OOS_authorized"] is False
    assert len(json.dumps(summary).encode("utf-8")) < 16384
