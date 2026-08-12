import json
from pathlib import Path

from src.phase6_m2 import M2_OUTPUT_ROOT, M2_PROTOCOL_ID, M2_RUNNER_NAMESPACE, m2_fingerprints


ROOT = Path(__file__).resolve().parents[1]


def test_m2_generated_wrapper_fix_audit_locks_new_identity() -> None:
    audit = json.loads((ROOT / "docs/handoffs/2026-08-12_phase6_m2_generated_wrapper_fix_audit.json").read_text(encoding="utf-8"))
    assert audit["branch"] == "agent/phase6-m2-generated-wrapper-fix"
    assert audit["implementation_commit"] == "29f61a5"
    assert audit["draft_pr"] == "https://github.com/nieying-code/phrase3/pull/44"
    assert audit["base_merge_sha"] == "007c6ccf0c881466cfa556ca17dac283eea7a2f0"
    assert audit["failed_run"] == {
        "run_id": "m2dev_v1_20260812_V1_seed2026081201_beta0p90_profileC0",
        "status": "stage_failure",
        "stage": "scenario_generation",
        "gurobi_call_count": 0,
        "preserved_in_output_root": "outputs/phase6_m2_supply_disruption_v1",
    }
    assert audit["replacement_identity"] == {
        "protocol_id": M2_PROTOCOL_ID,
        "runner_namespace": M2_RUNNER_NAMESPACE,
        "output_root": M2_OUTPUT_ROOT,
    }
    actual = m2_fingerprints(
        project_root=ROOT,
        config_path=ROOT / "configs/phase6_m2_supply_disruption.yaml",
        runner_config_path=ROOT / "configs/phase6_m2_runner.yaml",
    )
    assert audit["approved_fingerprints"] == actual
    assert audit["real_wrapper_boundary_test"] == {
        "tier": "V1", "scenario_count": 50,
        "solver_call_seconds": 120.0, "gurobi_called": False,
    }
    assert set(audit["execution_counts_in_fix_pr"].values()) == {0}
    assert audit["validation"] == {
        "focused_m2_tests_passed": 47,
        "ordinary_regression_passed": 281,
        "phase5_end_to_end_passed": 6,
        "compileall_passed": True,
        "git_diff_check_passed": True,
    }
