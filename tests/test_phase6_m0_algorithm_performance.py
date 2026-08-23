from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

import src.phase6_m0_algorithm_performance as performance
from src.phase6_m0_algorithm_performance_status import main as status_main
from src.phase6_protocol import load_phase6_matrix


ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "configs/phase6_experiment_matrix.yaml"
RUNNER_PATH = ROOT / "configs/phase6_m0_algorithm_performance_runner.yaml"
APPROVAL_PATH = ROOT / "configs/phase6_m0_algorithm_performance_approval_v1_0.yaml"


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_frozen_matrix_is_exactly_21_primary_runs_and_246_executions():
    matrix = load_phase6_matrix(MATRIX_PATH)
    cases = performance.build_performance_cases(matrix)
    assert len(cases) == 21
    assert sum(row.algorithm_execution_count for row in cases) == 246
    assert {tier: sum(row.tier_id == tier for row in cases) for tier in ("V1", "V2", "P1", "P2")} == {
        "V1": 3, "V2": 10, "P1": 5, "P2": 3,
    }
    assert {tier: sum(row.algorithm_execution_count for row in cases if row.tier_id == tier) for tier in ("V1", "V2", "P1", "P2")} == {
        "V1": 18, "V2": 180, "P1": 30, "P2": 18,
    }


@pytest.mark.parametrize("mutation", ["algorithm", "workload", "repetition"])
def test_matrix_mutations_are_rejected(mutation):
    matrix = copy.deepcopy(load_phase6_matrix(MATRIX_PATH))
    if mutation == "algorithm":
        matrix["algorithm_comparison"]["algorithms"][1] = "spw_ccg_cold"
    elif mutation == "workload":
        matrix["workload_estimation"]["E3_algorithm_executions"] = 245
    else:
        next(row for row in matrix["scale_tiers"] if row["id"] == "V2")["timing_repetitions"] = 2
    with pytest.raises(ValueError):
        performance.build_performance_cases(matrix)


def test_approval_scope_is_exact_and_other_experiments_remain_closed():
    runner = _yaml(RUNNER_PATH)
    approval = _yaml(APPROVAL_PATH)
    expected = {
        "M0_E3_algorithm_performance_authorized": True,
        "M2_formal_authorized": False,
        "M2_formal_OOS_authorized": False,
        "M2_1_authorized": False,
        "other_formal_experiments_authorized": False,
    }
    assert runner["authorizations"] == expected
    assert approval["authorizations"] == expected
    assert approval["execution_counts_in_this_revision"] == {
        "scenario_generation_count": 0,
        "gurobi_call_count": 0,
        "algorithm_performance_runs": 0,
    }


def _mock_context(tmp_path: Path):
    matrix = load_phase6_matrix(MATRIX_PATH)
    return {
        "runner": {
            "matrix_path": "matrix.yaml",
            "e3_runner_config_path": "runner.yaml",
            "output_root": "outputs/performance",
            "formal_subdirectory": "formal/primary",
        },
        "approval": {"reviewed_gate_evidence": {"final_projection_audit_sha256": "a" * 64}},
        "matrix": matrix,
        "e3_config": {},
        "cases": performance.build_performance_cases(matrix),
        "fingerprints": {
            "scientific_config_sha256": "1" * 64,
            "runner_config_sha256": "2" * 64,
            "e3_component_sha256": "3" * 64,
            "environment_sha256": "4" * 64,
            "algorithm_performance_orchestrator_sha256": "5" * 64,
        },
    }


def test_missing_explicit_authorization_rejects_before_preflight(monkeypatch, tmp_path):
    called = False
    def forbidden(**kwargs):
        nonlocal called
        called = True
    monkeypatch.setattr(performance, "validate_preflight", forbidden)
    with pytest.raises(RuntimeError, match="explicit"):
        performance.run_batch(
            root=tmp_path, runner_path=tmp_path / "runner.yaml",
            approval_path=tmp_path / "approval.yaml", authorize=False,
            run_id_prefix="formal_m0_e3",
        )
    assert called is False


@pytest.mark.parametrize("run_id", ["../escape", "a/b", "a\\b", "C:bad", "bad space"])
def test_unsafe_run_id_prefix_is_rejected_before_preflight(monkeypatch, tmp_path, run_id):
    monkeypatch.setattr(performance, "validate_preflight", lambda **kwargs: pytest.fail("preflight reached"))
    with pytest.raises(ValueError, match="unsafe"):
        performance.run_batch(
            root=tmp_path, runner_path=tmp_path / "r", approval_path=tmp_path / "a",
            authorize=True, run_id_prefix=run_id,
        )


def test_complete_primary_batch_runs_in_frozen_serial_order(monkeypatch, tmp_path):
    context = _mock_context(tmp_path)
    monkeypatch.setattr(performance, "validate_preflight", lambda **kwargs: context)
    observed = []
    def executor(**kwargs):
        observed.append((kwargs["tier_id"], kwargs["seed"], kwargs["run_id"]))
        return {"status": "optimal"}
    projections = []
    def projection(**kwargs):
        projections.append(len(observed))
        final = len(observed) == 21
        return {
            "status": "complete" if final else "incomplete",
            "completed_primary_run_count": len(observed),
            "completed_algorithm_execution_count": 246 if final else 0,
            "M0_E3_algorithm_performance_gate_passed": final,
        }
    monkeypatch.setattr(performance, "update_batch_projection", projection)
    result = performance.run_batch(
        root=tmp_path, runner_path=tmp_path / "runner.yaml",
        approval_path=tmp_path / "approval.yaml", authorize=True,
        run_id_prefix="formal_m0_e3", run_executor=executor,
    )
    assert [(tier, seed) for tier, seed, _ in observed] == [
        (case.tier_id, case.seed) for case in context["cases"]
    ]
    assert projections == list(range(1, 22))
    assert result["M0_E3_algorithm_performance_gate_passed"] is True


def test_nonoptimal_primary_stops_the_batch(monkeypatch, tmp_path):
    context = _mock_context(tmp_path)
    monkeypatch.setattr(performance, "validate_preflight", lambda **kwargs: context)
    calls = []
    def executor(**kwargs):
        calls.append(kwargs["run_id"])
        return {"status": "time_limit"}
    monkeypatch.setattr(performance, "update_batch_projection", lambda **kwargs: {
        "status": "incomplete", "M0_E3_algorithm_performance_gate_passed": False,
    })
    result = performance.run_batch(
        root=tmp_path, runner_path=tmp_path / "runner.yaml",
        approval_path=tmp_path / "approval.yaml", authorize=True,
        run_id_prefix="formal_m0_e3", run_executor=executor,
    )
    assert len(calls) == 1
    assert result["M0_E3_algorithm_performance_gate_passed"] is False


def test_runner_exception_writes_bounded_terminal_evidence_and_stops(monkeypatch, tmp_path):
    context = _mock_context(tmp_path)
    monkeypatch.setattr(performance, "validate_preflight", lambda **kwargs: context)
    calls = 0
    def executor(**kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        performance.run_batch(
            root=tmp_path, runner_path=tmp_path / "runner.yaml",
            approval_path=tmp_path / "approval.yaml", authorize=True,
            run_id_prefix="formal_m0_e3", run_executor=executor,
        )
    assert calls == 1
    evidence = json.loads((tmp_path / "outputs/performance/formal/primary/experiments/phase6/algorithm_performance_orchestrator_failure.json").read_text(encoding="utf-8"))
    assert evidence["status"] == "runner_exception"
    assert evidence["M0_E3_algorithm_performance_gate_passed"] is False


def test_status_reader_rejects_oversized_input(tmp_path, capsys):
    base = tmp_path / "formal/primary/experiments/phase6"
    base.mkdir(parents=True)
    (base / "algorithm_performance_status_summary.json").write_bytes(b" " * 16385)
    assert status_main(["--output", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "missing_or_oversized"


def test_reviewed_evidence_hashes_and_counts_are_machine_bound():
    approval = _yaml(APPROVAL_PATH)
    actual = approval["approved_fingerprints"]
    performance._validate_reviewed_evidence(ROOT, approval, actual)


def test_reviewed_text_evidence_hash_is_checkout_line_ending_invariant(tmp_path):
    lf = tmp_path / "lf.json"
    crlf = tmp_path / "crlf.json"
    lf.write_bytes(b'{\n  "value": 1\n}\n')
    crlf.write_bytes(b'{\r\n  "value": 1\r\n}\r\n')
    assert performance._sha256_lf_text(lf) == performance._sha256_lf_text(crlf)


def test_orchestrator_hash_and_artifacts_are_exactly_approved():
    approval = _yaml(APPROVAL_PATH)
    assert performance.algorithm_performance_orchestrator_sha256(ROOT) == approval["approved_fingerprints"]["algorithm_performance_orchestrator_sha256"]
    assert performance.sha256_file(RUNNER_PATH) == approval["artifact_sha256"]["runner_config"]
    assert performance.sha256_file(ROOT / "src/phase6_m0_algorithm_performance.py") == approval["artifact_sha256"]["orchestrator_module"]
    assert performance.sha256_file(ROOT / "src/run_phase6_m0_algorithm_performance.py") == approval["artifact_sha256"]["cli"]
    assert performance.sha256_file(ROOT / "src/phase6_m0_algorithm_performance_status.py") == approval["artifact_sha256"]["status_module"]


def test_no_algorithm_performance_results_exist_in_design_revision():
    assert not (ROOT / "outputs/phase6_m0_e3_algorithm_performance_v1_0").exists()
