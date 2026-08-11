from __future__ import annotations

import csv
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import src.phase6_m1_development as development
from src.phase6_m1_status import read_status
from src.phase6_io import atomic_write_csv, atomic_write_json
from src.reproducibility import sha256_file


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/phase6_m1_procurement_cap.yaml"
RUNNER_PATH = ROOT / "configs/phase6_m1_runner.yaml"
FINGERPRINTS = {
    "scientific_config_sha256": "1" * 64,
    "e3_component_sha256": "2" * 64,
    "family_component_sha256": "3" * 64,
    "runner_config_sha256": "4" * 64,
    "environment_sha256": "5" * 64,
}


def _science(*, case, progress, **_kwargs) -> dict[str, Any]:
    progress("minimum_feasible_reserve", {})
    progress("complete_extensive_optimum", {})
    return {
        "tier_id": case.tier_id,
        "seed": case.seed,
        "beta": case.beta,
        "kappa": case.kappa,
        "substantive_activation": False,
        "fixed_autonomous_reserve_policies": [
            {"rho": rho, "regular_purchase_sha256": str(index + 1) * 64}
            for index, rho in enumerate((0.0, 0.1, 0.3, 0.5))
        ],
    }


def _registry_process(output_root: str, index: int) -> str:
    row = {
        field: "" for field in development.REGISTRY_FIELDS
    }
    row.update(
        {
            "run_id": f"concurrent-{index}",
            "case_id": f"case-{index}",
            "status": "optimal",
        }
    )
    development.upsert_development_registry(Path(output_root), row)
    return row["run_id"]


def _projection_process(
    output_root: str,
    config: dict[str, Any],
    fingerprints: dict[str, str],
) -> bool:
    payload = development.update_development_projection(
        output_root=Path(output_root),
        config=config,
        fingerprints=fingerprints,
    )
    return payload["formal_extension_authorized"]


def _write_approval(path: Path, fingerprints: dict[str, str]) -> None:
    path.write_text(
        "approval_id: phase6_m1_development_execution_v1\n"
        "status: frozen_for_development_execution\n"
        "scientific_protocol: phase6_m1_procurement_cap_v1_0\n"
        "runner_namespace: phase6_m1_procurement_cap\n"
        "matrix_case_count: 63\n"
        "explicit_cli_authorization_required: true\n"
        "formal_extension_authorized: false\n"
        "accept_m0_authorization: false\n"
        "approved_fingerprints:\n"
        + "".join(f"  {key}: {value}\n" for key, value in fingerprints.items()),
        encoding="utf-8",
    )


def _run_case(tmp_path: Path, run_id: str, executor=_science):
    config = development.load_m1_config(CONFIG_PATH)
    case = development.build_development_cases(config)[0]
    return development.run_development_case(
        project_root=ROOT,
        output_root=tmp_path,
        matrix_path=ROOT / config["base_model"]["matrix_path"],
        config=config,
        fingerprints=FINGERPRINTS,
        locked_environment={"python": "3.12.10"},
        source={"commit_sha": "a" * 40, "tree_sha": "b" * 40},
        case=case,
        run_id=run_id,
        science_executor=executor,
    )


def _populate_projection(
    output_root: Path,
    *,
    substantive_case_ids: set[str],
) -> dict[str, Any]:
    config = development.load_m1_config(CONFIG_PATH)
    rows = []
    for case in development.build_development_cases(config):
        run_id = f"primary-{case.case_id}"
        directory = output_root / "development" / "runs" / run_id
        directory.mkdir(parents=True)
        result = {
            "run_id": run_id,
            "parent_run_id": None,
            "case_id": case.case_id,
            "case": case.as_dict(),
            "status": "optimal",
            "finalized": True,
            "wall_seconds": 1.0,
            "git_sha": "a" * 40,
            "git_tree_sha": "b" * 40,
            "science": {
                "substantive_activation": case.case_id in substantive_case_ids,
            },
            "fingerprints": FINGERPRINTS,
        }
        result_path = directory / "result.json"
        manifest_path = directory / "manifest.json"
        checkpoint_path = directory / "checkpoint.json"
        status_path = directory / "status_summary.json"
        heartbeat_path = directory / "heartbeat.json"
        atomic_write_json(result_path, result)
        for path in (checkpoint_path, status_path, heartbeat_path):
            atomic_write_json(path, {"run_id": run_id, "status": "optimal"})
        atomic_write_json(
            manifest_path,
            {
                "result_sha256": sha256_file(result_path),
                "checkpoint_sha256": sha256_file(checkpoint_path),
                "status_summary_sha256": sha256_file(status_path),
                "heartbeat_sha256": sha256_file(heartbeat_path),
                "run_id": run_id,
                "case_id": case.case_id,
                "fingerprints": FINGERPRINTS,
                "source": {"commit_sha": "a" * 40, "tree_sha": "b" * 40},
            },
        )
        row = {field: "" for field in development.REGISTRY_FIELDS}
        row.update(
            {
                "run_id": run_id,
                "case_id": case.case_id,
                "tier_id": case.tier_id,
                "seed": case.seed,
                "beta": case.beta,
                "kappa": "unbounded" if case.kappa is None else case.kappa,
                "status": "optimal",
                "substantive_activation": str(case.case_id in substantive_case_ids),
                "wall_seconds": 1.0,
                **FINGERPRINTS,
                "result_path": str(result_path),
                "manifest_path": str(manifest_path),
                "manifest_sha256": sha256_file(manifest_path),
            }
        )
        rows.append(row)
    atomic_write_csv(
        output_root / "development" / "development_run_registry.csv",
        development.REGISTRY_FIELDS,
        rows,
    )
    return config


def test_frozen_matrix_is_exact_63_case_cartesian_product() -> None:
    config = development.load_m1_config(CONFIG_PATH)
    cases = development.build_development_cases(config)
    assert len(cases) == len({case.case_id for case in cases}) == 63
    assert {case.tier_id for case in cases} == {"V1"}
    assert {case.seed for case in cases} == {2026081101, 2026081102, 2026081103}
    assert {case.beta for case in cases} == {0.9, 1.1, 1.3}
    assert {case.kappa for case in cases} == {
        None, 1.5, 1.3, 1.2, 1.1, 1.0, 0.8
    }
    assert all(
        case.cap_config == {"enabled": False, "kappa": None}
        for case in cases if case.kappa is None
    )


def test_frozen_approval_and_machine_audit_lock_current_m1_fingerprints() -> None:
    config = development.load_m1_config(CONFIG_PATH)
    actual = development.m1_fingerprints(
        project_root=ROOT,
        config_path=CONFIG_PATH,
        runner_config_path=RUNNER_PATH,
    )
    expected = {
        "scientific_config_sha256": "6439d8a1945e44985cb1c8b20a20b7641617ed9a160db554680f3dc4680aa8c8",
        "e3_component_sha256": "994e72479f0994c134d112bef1af78421ee3cca25593ab6a9d1146e153afbde2",
        "family_component_sha256": "05065fba9dd69665bf556da2e6b44fde7e0f73d476172811aeb4d662b74a839d",
        "runner_config_sha256": "4e39efe184877da9892e63852298bad4f9662b6d09af7ef5fedd6c4a09a13f3a",
        "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
    }
    approval = development.load_development_approval(
        ROOT / development.M1_DEVELOPMENT_APPROVAL
    )
    audit = json.loads(
        (ROOT / "docs/handoffs/2026-08-11_phase6_m1_development_runner_audit.json")
        .read_text(encoding="utf-8")
    )
    assert config["status"] == "frozen_for_development_execution"
    assert approval["approved_fingerprints"] == expected
    assert audit["approved_fingerprints"] == expected
    assert {
        key: approval[key]
        for key in (
            "approval_id",
            "status",
            "scientific_protocol",
            "runner_namespace",
            "matrix_case_count",
            "explicit_cli_authorization_required",
            "formal_extension_authorized",
            "accept_m0_authorization",
        )
    } == {
        "approval_id": "phase6_m1_development_execution_v1",
        "status": "frozen_for_development_execution",
        "scientific_protocol": "phase6_m1_procurement_cap_v1_0",
        "runner_namespace": "phase6_m1_procurement_cap",
        "matrix_case_count": 63,
        "explicit_cli_authorization_required": True,
        "formal_extension_authorized": False,
        "accept_m0_authorization": False,
    }
    guards = audit["execution_guards"]
    assert guards["complete_extensive_solver_call_seconds"] == 120
    assert guards["native_solver_time_limit_is_terminal_timeout"] is True
    assert guards["matrix_load_and_finalization_in_unified_lifecycle"] is True
    assert guards["keyboard_interrupt_terminal_status"] == "interrupted"
    assert guards["resolved_run_path_must_remain_under_m1_output_root"] is True
    assert guards["memory_metric"] == "sampled_process_peak_rss_mb"
    assert guards["approval_metadata_exactly_validated"] is True
    assert {
        key: value for key, value in actual.items() if key != "environment_sha256"
    } == {
        key: value for key, value in expected.items() if key != "environment_sha256"
    }
    assert len(actual["environment_sha256"]) == 64
    int(actual["environment_sha256"], 16)
    assert audit["environment_fingerprint_scope"] == {
        "approved_value": "local_controlled_gurobi_execution_host",
        "cross_platform_CI_expected_to_match": False,
        "future_M1_development_runs_must_match_approved_local_value": True,
    }
    assert audit["execution_counts"] == {
        "development_cases_run": 0,
        "pilot_runs": 0,
        "formal_runs": 0,
        "m0_e3_runs": 0,
    }
    assert audit["activation"]["formal_extension_authorized"] is False


def test_missing_explicit_authorization_fails_before_environment_or_scenarios(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        development,
        "validate_locked_environment",
        lambda *_args, **_kwargs: pytest.fail("environment must not be reached"),
    )
    with pytest.raises(PermissionError, match="authorize-development-execution"):
        development.validate_development_preflight(
            project_root=ROOT,
            config_path=CONFIG_PATH,
            runner_config_path=RUNNER_PATH,
            approval_path=ROOT / "unused.yaml",
            authorize_development_execution=False,
        )


def test_nonfrozen_status_fails_before_environment_or_scenarios(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = CONFIG_PATH.read_text(encoding="utf-8").replace(
        "frozen_for_development_execution", "candidate_design_pending_review"
    )
    path = tmp_path / "candidate.yaml"
    path.write_text(config, encoding="utf-8")
    monkeypatch.setattr(
        development,
        "validate_locked_environment",
        lambda *_args, **_kwargs: pytest.fail("environment must not be reached"),
    )
    with pytest.raises(RuntimeError, match="not frozen"):
        development.validate_development_preflight(
            project_root=ROOT,
            config_path=path,
            runner_config_path=RUNNER_PATH,
            approval_path=ROOT / "unused.yaml",
            authorize_development_execution=True,
        )


def test_fingerprint_mismatch_and_m0_authorization_cannot_authorize_m1(
    tmp_path: Path,
    monkeypatch,
) -> None:
    approval = tmp_path / "approval.yaml"
    _write_approval(approval, FINGERPRINTS)
    monkeypatch.setattr(
        development, "validate_locked_environment", lambda *_args: {}
    )
    monkeypatch.setattr(
        development,
        "m1_fingerprints",
        lambda **_kwargs: {**FINGERPRINTS, "runner_config_sha256": "9" * 64},
    )
    with pytest.raises(RuntimeError, match="fingerprint mismatch"):
        development.validate_development_preflight(
            project_root=ROOT,
            config_path=CONFIG_PATH,
            runner_config_path=RUNNER_PATH,
            approval_path=approval,
            authorize_development_execution=True,
        )
    runner = RUNNER_PATH.read_text(encoding="utf-8")
    assert "accept_M0_authorization: false" in runner
    assert "accept_M0_registry: false" in runner
    assert "accept_M0_projection: false" in runner


@pytest.mark.parametrize(
    "field",
    [
        "approval_id",
        "status",
        "scientific_protocol",
        "runner_namespace",
        "matrix_case_count",
        "explicit_cli_authorization_required",
        "formal_extension_authorized",
        "accept_m0_authorization",
    ],
)
def test_approval_metadata_is_exactly_enforced(tmp_path: Path, field: str) -> None:
    approval = tmp_path / "approval.yaml"
    _write_approval(approval, FINGERPRINTS)
    payload = approval.read_text(encoding="utf-8")
    if field in {"matrix_case_count"}:
        payload = payload.replace("matrix_case_count: 63", "matrix_case_count: 62")
    elif field in {
        "explicit_cli_authorization_required",
        "formal_extension_authorized",
        "accept_m0_authorization",
    }:
        old = f"{field}: " + ("true" if field == "explicit_cli_authorization_required" else "false")
        payload = payload.replace(old, f"{field}: wrong")
    else:
        lines = payload.splitlines()
        lines = [
            f"{field}: wrong" if line.startswith(f"{field}:") else line
            for line in lines
        ]
        payload = "\n".join(lines) + "\n"
    approval.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="approval metadata mismatch"):
        development.load_development_approval(approval)


def test_extensive_optimum_receives_frozen_v1_solver_limit(monkeypatch) -> None:
    config = development.load_m1_config(CONFIG_PATH)
    case = development.build_development_cases(config)[0]
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        development,
        "generate_m1_data",
        lambda *_args, **_kwargs: SimpleNamespace(
            data=object(), tier=SimpleNamespace(solver_call_seconds=120.0)
        ),
    )
    monkeypatch.setattr(
        development,
        "solve_minimum_feasible_reserve",
        lambda *_args, **_kwargs: SimpleNamespace(
            status="optimal", reserve=0.0, closed_form_difference=0.0
        ),
    )

    def extensive(*_args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(status="master_time_limit", objective=None)

    monkeypatch.setattr(development, "solve_m1_endogenous_extensive", extensive)
    with pytest.raises(development.DevelopmentStageError) as caught:
        development.execute_development_case_science(
            project_root=ROOT,
            matrix={"budget_plan": {"reference_budget_by_tier": {"V1": 100.0}}},
            matrix_path=ROOT / "configs/phase6_experiment_matrix.yaml",
            config=config,
            case=case,
            progress=lambda *_args: None,
        )
    assert seen["time_limit_seconds"] == 120.0
    assert caught.value.solver_status == "master_time_limit"


def test_native_solver_timeout_becomes_timeout_terminal(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(development, "capture_runtime_context", lambda **_kwargs: {})

    def timed_out(**_kwargs):
        raise development.DevelopmentStageError(
            "complete_extensive_optimum",
            "master_time_limit",
            "frozen solver call reached its limit",
        )

    result = _run_case(tmp_path, "native-timeout", timed_out)
    assert result["status"] == "timeout"
    assert result["failure"]["stage"] == "complete_extensive_optimum"
    assert result["failure"]["solver_status"] == "master_time_limit"
    assert result["failure_counts"]["timeout"] == 1


def test_matrix_load_failure_is_finalized_as_runner_exception(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        development,
        "load_phase6_matrix",
        lambda *_args: (_ for _ in ()).throw(ValueError("bad matrix")),
    )
    monkeypatch.setattr(development, "capture_runtime_context", lambda **_kwargs: {})
    result = _run_case(tmp_path, "matrix-failure")
    assert result["status"] == "runner_exception"
    assert result["failure"]["stage"] == "matrix_load"
    assert (tmp_path / "development/runs/matrix-failure/manifest.json").is_file()


def test_runtime_context_failure_is_finalized_as_runner_exception(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        development,
        "capture_runtime_context",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("context failed")),
    )
    result = _run_case(tmp_path, "context-failure")
    assert result["status"] == "runner_exception"
    assert result["failure"]["stage"] == "runtime_context"
    assert result["memory_metric"] == "sampled_process_peak_rss_mb"


def test_manifest_failure_is_retried_as_runner_exception_terminal(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(development, "capture_runtime_context", lambda **_kwargs: {})
    original = development.atomic_write_json
    failed = False

    def fail_once(path, payload):
        nonlocal failed
        if Path(path).name == "manifest.json" and not failed:
            failed = True
            raise PermissionError("synthetic manifest failure")
        return original(path, payload)

    monkeypatch.setattr(development, "atomic_write_json", fail_once)
    result = _run_case(tmp_path, "manifest-failure")
    assert result["status"] == "runner_exception"
    assert result["failure"]["stage"] == "artifact_finalization"
    directory = tmp_path / "development/runs/manifest-failure"
    assert (directory / "manifest.json").is_file()


def test_registry_failure_is_retried_as_runner_exception_terminal(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(development, "capture_runtime_context", lambda **_kwargs: {})
    original = development.upsert_development_registry
    failed = False

    def fail_once(output_root, row):
        nonlocal failed
        if not failed:
            failed = True
            raise PermissionError("synthetic registry failure")
        return original(output_root, row)

    monkeypatch.setattr(development, "upsert_development_registry", fail_once)
    result = _run_case(tmp_path, "registry-failure")
    assert result["status"] == "runner_exception"
    assert result["failure"]["stage"] == "registry_finalization"
    rows = development._read_registry(
        tmp_path / "development/development_run_registry.csv"
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "runner_exception"


def test_unsafe_prefix_fails_before_preflight(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        development,
        "validate_development_preflight",
        lambda **_kwargs: pytest.fail("preflight must not be reached"),
    )
    with pytest.raises(ValueError, match="run_id"):
        development.run_development_matrix(
            project_root=ROOT,
            config_path=CONFIG_PATH,
            runner_config_path=RUNNER_PATH,
            approval_path=tmp_path / "unused.yaml",
            authorize_development_execution=True,
            run_id_prefix="../escape",
        )


@pytest.mark.parametrize(
    "run_id",
    ["../escape", "a/b", r"a\b", "..", "C:absolute"],
)
def test_unsafe_run_id_is_rejected_for_writes_and_status_reads(
    tmp_path: Path, run_id: str
) -> None:
    with pytest.raises(ValueError, match="run_id"):
        _run_case(tmp_path, run_id)
    with pytest.raises(ValueError, match="run_id"):
        read_status(tmp_path, run_id)
    assert not (tmp_path.parent / "escape").exists()


@pytest.mark.parametrize(
    ("executor", "expected_status"),
    [
        (_science, "optimal"),
        (lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("failed")), "stage_failure"),
        (lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("timeout")), "timeout"),
    ],
)
def test_terminal_run_ids_are_immutable(
    tmp_path: Path,
    monkeypatch,
    executor,
    expected_status: str,
) -> None:
    monkeypatch.setattr(development, "capture_runtime_context", lambda **_kwargs: {})
    first = _run_case(tmp_path, f"immutable-{expected_status}", executor)
    assert first["status"] == expected_status
    with pytest.raises(ValueError, match="immutable"):
        _run_case(tmp_path, f"immutable-{expected_status}", _science)


def test_interruption_preserves_checkpoint_and_requires_new_run_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(development, "capture_runtime_context", lambda **_kwargs: {})

    def interrupted(*, progress, **_kwargs):
        progress("complete_extensive_optimum", {})
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _run_case(tmp_path, "interrupted", interrupted)
    directory = tmp_path / "development" / "runs" / "interrupted"
    checkpoint = json.loads((directory / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "interrupted"
    assert checkpoint["current_stage"] == "complete_extensive_optimum"
    with pytest.raises(ValueError, match="immutable"):
        _run_case(tmp_path, "interrupted", _science)


def test_gate_requires_three_optimal_seeds_and_two_substantive_activations(
    tmp_path: Path,
) -> None:
    config = development.load_m1_config(CONFIG_PATH)
    target = {
        case.case_id
        for case in development.build_development_cases(config)
        if case.beta == 1.1 and case.kappa == 1.2 and case.seed != 2026081103
    }
    config = _populate_projection(tmp_path, substantive_case_ids=target)
    projection = development.update_development_projection(
        output_root=tmp_path,
        config=config,
        fingerprints=FINGERPRINTS,
    )
    assert projection["verified_primary_run_count"] == 63
    assert projection["development_activation_gate_passed"] is True
    assert projection["formal_extension_authorized"] is False
    assert [(row["beta"], row["kappa"]) for row in projection["passed_combinations"]] == [
        (1.1, 1.2)
    ]


def test_no_activation_stops_without_parameter_chasing(tmp_path: Path) -> None:
    config = _populate_projection(tmp_path, substantive_case_ids=set())
    projection = development.update_development_projection(
        output_root=tmp_path,
        config=config,
        fingerprints=FINGERPRINTS,
    )
    assert projection["status"] == "completed_no_activation"
    assert projection["development_activation_gate_passed"] is False
    assert projection["formal_extension_authorized"] is False
    assert projection["stop_reason"] == "no_preregistered_combination_passed"
    assert projection["selection_metrics_excluded"] == [
        "cost", "service_level", "P95", "CVaR", "manual_trend"
    ]


@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("run_id", "wrong-run"),
        ("parent_run_id", "wrong-parent"),
        ("case_id", "wrong-case"),
        ("tier_id", "V2"),
        ("seed", "99"),
        ("beta", "9.9"),
        ("kappa", "9.9"),
        ("status", "timeout"),
        ("substantive_activation", "True"),
        ("wall_seconds", "9.9"),
        ("manifest_sha256", "0" * 64),
    ],
)
def test_registry_identity_or_hash_tampering_is_rejected(
    tmp_path: Path,
    field: str,
    tampered: str,
) -> None:
    _populate_projection(tmp_path, substantive_case_ids=set())
    row = development._read_registry(
        tmp_path / "development" / "development_run_registry.csv"
    )[0]
    row[field] = tampered
    with pytest.raises(ValueError, match="mismatch"):
        development.validate_run_artifacts(row)


def test_terminal_summary_tampering_is_rejected(tmp_path: Path) -> None:
    _populate_projection(tmp_path, substantive_case_ids=set())
    row = development._read_registry(
        tmp_path / "development" / "development_run_registry.csv"
    )[0]
    status_path = Path(row["result_path"]).parent / "status_summary.json"
    atomic_write_json(status_path, {"status": "tampered"})
    with pytest.raises(ValueError, match="terminal artifact mismatch"):
        development.validate_run_artifacts(row)


def test_status_reader_is_bounded_and_never_parses_large_result(tmp_path: Path) -> None:
    directory = tmp_path / "development" / "runs" / "bounded"
    directory.mkdir(parents=True)
    atomic_write_json(
        directory / "status_summary.json",
        {
            "status": "stage_failure",
            "failure": development.compact_failure(
                {"stage": "solver", "status": "failed", "message": "x" * 100_000}
            ),
        },
    )
    (directory / "result.json").write_text("{" + "x" * 1_000_000, encoding="utf-8")
    payload = read_status(tmp_path, "bounded")
    assert payload["payload"]["status"] == "stage_failure"
    assert len(payload["payload"]["failure"]["message"]) == 1000
    assert (directory / "result.json").stat().st_size > 1_000_000


def test_real_multiprocess_registry_and_projection_writes_are_serialized(
    tmp_path: Path,
) -> None:
    with ProcessPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(
            _registry_process,
            [str(tmp_path)] * 12,
            range(12),
        ))
    registry = development._read_registry(
        tmp_path / "development" / "development_run_registry.csv"
    )
    assert len(registry) == len(set(ids)) == 12

    complete_root = tmp_path / "projection"
    config = _populate_projection(complete_root, substantive_case_ids=set())
    with ProcessPoolExecutor(max_workers=3) as pool:
        results = [
            future.result()
            for future in [
                pool.submit(
                    _projection_process,
                    str(complete_root),
                    config,
                    FINGERPRINTS,
                )
                for _ in range(3)
            ]
        ]
    assert results == [False, False, False]
    projection = json.loads(
        (complete_root / "development" / "development_activation_projection.json")
        .read_text(encoding="utf-8")
    )
    assert projection["verified_primary_run_count"] == 63
    assert projection["formal_extension_authorized"] is False
