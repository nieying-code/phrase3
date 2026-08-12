from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pytest

import src.phase6_m2_development as development
from src.phase6_io import atomic_write_csv, atomic_write_json
from src.phase6_m2_status import read_status
from src.reproducibility import sha256_file


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/phase6_m2_supply_disruption.yaml"
RUNNER = ROOT / "configs/phase6_m2_runner.yaml"
FINGERPRINTS = {
    "scientific_config_sha256": "1" * 64,
    "e3_component_sha256": "2" * 64,
    "family_component_sha256": "3" * 64,
    "runner_config_sha256": "4" * 64,
    "environment_sha256": "5" * 64,
}


def _registry_process(output_root: str, index: int) -> str:
    row = {field: "" for field in development.REGISTRY_FIELDS}
    row.update({"run_id": f"concurrent-{index}", "case_id": f"case-{index}", "status": "optimal"})
    development.upsert_development_registry(Path(output_root), row)
    return row["run_id"]


def _science(*, case, progress, **_kwargs) -> dict[str, Any]:
    progress("joint_scenario_generation", {})
    progress("complete_extensive_reserve_interval", {})
    return {
        "tier_id": case.tier_id, "seed": case.seed, "beta": case.beta,
        "profile_id": case.profile_id, "substantive_activation": False,
        "fixed_reserve_policies": [
            {"rho": rho, "regular_purchase_sha256": str(i + 1) * 64}
            for i, rho in enumerate((0.0, 0.1, 0.3, 0.5))
        ],
    }


def _run(tmp_path: Path, run_id: str, executor=_science):
    config = development.load_m2_config(CONFIG)
    return development.run_development_case(
        project_root=ROOT, output_root=tmp_path,
        matrix_path=ROOT / config["base_model"]["matrix_path"], config=config,
        fingerprints=FINGERPRINTS, locked_environment={"python": "3.12.10"},
        source={"commit_sha": "a" * 40, "tree_sha": "b" * 40},
        case=development.build_development_cases(config)[0], run_id=run_id,
        science_executor=executor,
    )


def _populate(output_root: Path, activated: set[str]) -> dict[str, Any]:
    config = development.load_m2_config(CONFIG)
    rows = []
    for case in development.build_development_cases(config):
        run_id = f"primary-{case.case_id}"
        directory = output_root / "development" / "runs" / run_id
        directory.mkdir(parents=True)
        result = {
            "run_id": run_id, "parent_run_id": None, "case_id": case.case_id,
            "case": case.as_dict(), "status": "optimal", "finalized": True,
            "wall_seconds": 1.0, "git_sha": "a" * 40, "git_tree_sha": "b" * 40,
            "science": {"substantive_activation": case.case_id in activated},
            "fingerprints": FINGERPRINTS,
        }
        paths = {name: directory / name for name in (
            "result.json", "manifest.json", "checkpoint.json",
            "status_summary.json", "heartbeat.json")}
        atomic_write_json(paths["result.json"], result)
        for name in ("checkpoint.json", "status_summary.json", "heartbeat.json"):
            atomic_write_json(paths[name], {"run_id": run_id, "status": "optimal"})
        atomic_write_json(paths["manifest.json"], {
            "result_sha256": sha256_file(paths["result.json"]),
            "checkpoint_sha256": sha256_file(paths["checkpoint.json"]),
            "status_summary_sha256": sha256_file(paths["status_summary.json"]),
            "heartbeat_sha256": sha256_file(paths["heartbeat.json"]),
            "run_id": run_id, "case_id": case.case_id,
            "fingerprints": FINGERPRINTS,
            "source": {"commit_sha": "a" * 40, "tree_sha": "b" * 40},
        })
        row = {field: "" for field in development.REGISTRY_FIELDS}
        row.update({
            "run_id": run_id, "case_id": case.case_id, "tier_id": case.tier_id,
            "seed": case.seed, "beta": case.beta, "profile_id": case.profile_id,
            "status": "optimal", "substantive_activation": str(case.case_id in activated),
            "wall_seconds": 1.0, **FINGERPRINTS,
            "result_path": str(paths["result.json"]),
            "manifest_path": str(paths["manifest.json"]),
            "manifest_sha256": sha256_file(paths["manifest.json"]),
        })
        rows.append(row)
    atomic_write_csv(output_root / "development/development_run_registry.csv",
                     development.REGISTRY_FIELDS, rows)
    return config


def test_frozen_matrix_is_exact_27_case_cartesian_product() -> None:
    cases = development.build_development_cases(development.load_m2_config(CONFIG))
    assert len(cases) == len({case.case_id for case in cases}) == 27
    assert {case.seed for case in cases} == {2026081201, 2026081202, 2026081203}
    assert {case.beta for case in cases} == {0.9, 1.1, 1.3}
    assert {case.profile_id for case in cases} == {"C0", "C1", "C2"}


def test_missing_authorization_and_candidate_status_fail_before_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(development, "validate_locked_environment",
                        lambda *_: pytest.fail("environment reached"))
    with pytest.raises(PermissionError):
        development.validate_development_preflight(
            project_root=ROOT, config_path=CONFIG, runner_config_path=RUNNER,
            approval_path=tmp_path / "missing", authorize_development_execution=False)
    candidate = tmp_path / "candidate.yaml"
    candidate.write_text(CONFIG.read_text(encoding="utf-8").replace(
        "frozen_for_development_execution", "candidate_design_pending_review"), encoding="utf-8")
    with pytest.raises(RuntimeError, match="not frozen"):
        development.validate_development_preflight(
            project_root=ROOT, config_path=candidate, runner_config_path=RUNNER,
            approval_path=tmp_path / "missing", authorize_development_execution=True)


def test_fingerprint_mismatch_and_m0_m1_authorization_are_rejected(tmp_path, monkeypatch) -> None:
    approval = tmp_path / "approval.yaml"
    approval.write_text(
        "approval_id: phase6_m2_development_execution_v1\n"
        "status: frozen_for_development_execution\n"
        "scientific_protocol: phase6_m2_supply_disruption_v1_0\n"
        "runner_namespace: phase6_m2_supply_disruption\n"
        "matrix_case_count: 27\n"
        "explicit_cli_authorization_required: true\n"
        "formal_extension_authorized: false\n"
        "accept_m0_or_m1_authorization: false\n"
        "approved_fingerprints:\n" + "".join(
            f"  {key}: {value}\n" for key, value in FINGERPRINTS.items()),
        encoding="utf-8",
    )
    monkeypatch.setattr(development, "validate_locked_environment", lambda *_: {})
    monkeypatch.setattr(development, "m2_fingerprints", lambda **_: {
        **FINGERPRINTS, "runner_config_sha256": "9" * 64})
    with pytest.raises(RuntimeError, match="fingerprint mismatch"):
        development.validate_development_preflight(
            project_root=ROOT, config_path=CONFIG, runner_config_path=RUNNER,
            approval_path=approval, authorize_development_execution=True)
    runner = RUNNER.read_text(encoding="utf-8")
    assert "accept_M0_or_M1_authorization: false" in runner
    assert "accept_M0_or_M1_registry: false" in runner
    assert "accept_M0_or_M1_projection: false" in runner


@pytest.mark.parametrize("run_id", ["../escape", "a/b", "a\\b", "..", ""])
def test_unsafe_run_ids_are_rejected(run_id: str) -> None:
    with pytest.raises(ValueError):
        development.validate_run_id(run_id)


@pytest.mark.parametrize("executor,status", [
    (_science, "optimal"),
    (lambda **_: (_ for _ in ()).throw(RuntimeError("failed")), "stage_failure"),
    (lambda **_: (_ for _ in ()).throw(TimeoutError("timeout")), "timeout"),
])
def test_terminal_run_ids_are_immutable(tmp_path, monkeypatch, executor, status) -> None:
    monkeypatch.setattr(development, "capture_runtime_context", lambda **_: {})
    assert _run(tmp_path, f"immutable-{status}", executor)["status"] == status
    with pytest.raises(ValueError, match="immutable"):
        _run(tmp_path, f"immutable-{status}")


def test_interruption_preserves_terminal_checkpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(development, "capture_runtime_context", lambda **_: {})
    def interrupt(*, progress, **_):
        progress("complete_extensive_reserve_interval", {})
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        _run(tmp_path, "interrupted", interrupt)
    payload = json.loads((tmp_path / "development/runs/interrupted/checkpoint.json").read_text(encoding="utf-8"))
    assert payload["status"] == "interrupted"


def test_native_solver_limit_becomes_timeout_terminal(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(development, "capture_runtime_context", lambda **_: {})
    def timeout(**_):
        raise development.DevelopmentStageError(
            "complete_extensive_optimum", "master_time_limit", "limit")
    result = _run(tmp_path, "native-timeout", timeout)
    assert result["status"] == "timeout"
    assert result["failure"]["solver_status"] == "master_time_limit"
    assert result["failure_counts"]["timeout"] == 1


def test_runtime_context_failure_is_finalized(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(development, "capture_runtime_context",
                        lambda **_: (_ for _ in ()).throw(RuntimeError("context")))
    result = _run(tmp_path, "context-failure")
    assert result["status"] == "runner_exception"
    assert result["failure"]["stage"] == "runtime_context"
    assert (tmp_path / "development/runs/context-failure/manifest.json").is_file()


def test_gate_requires_three_optimal_seeds_and_two_activations(tmp_path) -> None:
    config = development.load_m2_config(CONFIG)
    activated = {case.case_id for case in development.build_development_cases(config)
                 if case.beta == 1.1 and case.profile_id == "C1" and case.seed != 2026081203}
    projection = development.update_development_projection(
        output_root=tmp_path, config=_populate(tmp_path, activated), fingerprints=FINGERPRINTS)
    assert projection["verified_primary_run_count"] == 27
    assert projection["development_activation_gate_passed"] is True
    assert projection["formal_extension_authorized"] is False
    assert [(x["beta"], x["profile_id"]) for x in projection["passed_combinations"]] == [(1.1, "C1")]


def test_no_activation_stops_without_parameter_chasing(tmp_path) -> None:
    projection = development.update_development_projection(
        output_root=tmp_path, config=_populate(tmp_path, set()), fingerprints=FINGERPRINTS)
    assert projection["status"] == "completed_no_activation"
    assert projection["stop_reason"] == "no_preregistered_combination_passed"
    assert projection["formal_extension_authorized"] is False


def test_full_primary_execution_rejects_nonempty_controlled_root(tmp_path, monkeypatch) -> None:
    (tmp_path / "outputs/phase6_m2_supply_disruption_v1/development").mkdir(parents=True)
    (tmp_path / "outputs/phase6_m2_supply_disruption_v1/development/old.txt").write_text("old")
    monkeypatch.setattr(development, "validate_development_preflight", lambda **_: {
        "config": development.load_m2_config(CONFIG), "fingerprints": FINGERPRINTS,
        "locked_environment": {}, "source": {"commit_sha": "a" * 40, "tree_sha": "b" * 40},
    })
    with pytest.raises(RuntimeError, match="empty controlled"):
        development.run_development_matrix(
            project_root=tmp_path, config_path=CONFIG, runner_config_path=RUNNER,
            approval_path=tmp_path / "approval.yaml",
            authorize_development_execution=True, run_id_prefix="primary")


def test_artifact_tampering_is_rejected(tmp_path) -> None:
    _populate(tmp_path, set())
    row = development._read_registry(tmp_path / "development/development_run_registry.csv")[0]
    row["profile_id"] = "C9"
    with pytest.raises(ValueError, match="mismatch"):
        development.validate_run_artifacts(row)


def test_duplicate_primary_and_diagnostic_attempt_block_gate(tmp_path) -> None:
    config = _populate(tmp_path, set())
    rows = development._read_registry(tmp_path / "development/development_run_registry.csv")
    duplicate = dict(rows[0]); duplicate["run_id"] = "duplicate-primary"
    diagnostic = dict(rows[1]); diagnostic["run_id"] = "diagnostic"; diagnostic["parent_run_id"] = rows[1]["run_id"]
    atomic_write_csv(tmp_path / "development/development_run_registry.csv",
                     development.REGISTRY_FIELDS, [*rows, duplicate, diagnostic])
    projection = development.update_development_projection(
        output_root=tmp_path, config=config, fingerprints=FINGERPRINTS)
    assert projection["development_activation_gate_passed"] is False
    assert projection["formal_extension_authorized"] is False
    assert projection["duplicate_case_ids"]
    assert projection["diagnostic_run_ids"] == ["diagnostic"]


def test_status_reader_is_bounded_and_does_not_parse_result(tmp_path) -> None:
    directory = tmp_path / "development/runs/bounded"
    directory.mkdir(parents=True)
    atomic_write_json(directory / "status_summary.json", {
        "status": "stage_failure", "failure": development.compact_failure(
            {"stage": "solver", "status": "failed", "message": "x" * 100_000})})
    (directory / "result.json").write_text("{" + "x" * 1_000_000)
    payload = read_status(tmp_path, "bounded")
    assert len(payload["payload"]["failure"]["message"]) == 1000


def test_registry_lock_is_cross_process_safe(tmp_path) -> None:
    with ProcessPoolExecutor(max_workers=3) as pool:
        ids = list(pool.map(_registry_process, [str(tmp_path)] * 9, range(9)))
    rows = development._read_registry(tmp_path / "development/development_run_registry.csv")
    assert len(rows) == len(set(ids)) == 9
