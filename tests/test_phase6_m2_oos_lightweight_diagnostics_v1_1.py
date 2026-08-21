from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
from pathlib import Path

import pytest

from src import phase6_m2_oos_lightweight_diagnostics as diagnostics
from src.phase6_m2_formal_extension import formal_extension_fingerprints


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "docs/handoffs" / diagnostics.CSV_NAME
REPORT_PATH = ROOT / "docs/handoffs" / diagnostics.REPORT_NAME
AUDIT_PATH = ROOT / "docs/handoffs" / diagnostics.AUDIT_NAME
SCRIPT_PATH = ROOT / "src/phase6_m2_oos_lightweight_diagnostics.py"
FORMAL_CONFIG = ROOT / "configs/phase6_m2_formal_extension.yaml"
FORMAL_RUNNER = ROOT / "configs/phase6_m2_formal_extension_runner.yaml"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_audit() -> dict:
    return json.loads(AUDIT_PATH.read_text(encoding="utf-8"))


def normalize_csv_row(row: dict[str, str]) -> dict[str, object]:
    boolean_fields = {
        "zero_endogenous_reserve", "numerical_activation",
        "substantive_activation", "moderate_activation",
        "training_best_is_oos_mean_best",
        "training_best_is_oos_cvar_best",
        "training_best_is_oos_service_best",
    }
    integer_fields = {"training_seed", "test_seed"}
    string_fields = {
        "source_mechanism_run_id", "oos_run_id",
        "training_objective_ranking", "oos_mean_total_cost_ranking",
        "oos_cvar95_ranking", "oos_service_level_ranking",
        "training_best_strategy", "training_selected_best_fixed_strategy",
    }
    result: dict[str, object] = {}
    for key, value in row.items():
        if key in boolean_fields:
            result[key] = value == "True"
        elif key in integer_fields:
            result[key] = int(value)
        elif key in string_fields:
            result[key] = value
        elif value == "":
            result[key] = None
        else:
            result[key] = float(value)
    return result


def test_reviewed_audits_counts_fingerprints_and_orchestrator_are_locked() -> None:
    audit = load_audit()
    assert sha256(ROOT / diagnostics.PR58_REL) == diagnostics.PR58_SHA
    assert sha256(ROOT / diagnostics.PR60_REL) == diagnostics.PR60_SHA
    assert audit["reviewed_inputs"] == {
        "pr58_audit_path": diagnostics.PR58_REL,
        "pr58_audit_sha256": diagnostics.PR58_SHA,
        "pr60_audit_path": diagnostics.PR60_REL,
        "pr60_audit_sha256": diagnostics.PR60_SHA,
    }
    assert audit["execution_baseline"] == {
        "pr60_merge_commit": "8fb9684e7b27a6c0034613c394697efbac69c7c0",
        "base_git_sha": "8fb9684e7b27a6c0034613c394697efbac69c7c0",
        "base_git_tree_sha": "8eb925963480a8795b3510bb8c1e72294b188309",
        "working_tree_clean_before_branch": True,
    }
    assert audit["fingerprints"] == diagnostics.FINGERPRINTS
    assert formal_extension_fingerprints(
        ROOT, FORMAL_CONFIG, FORMAL_RUNNER
    ) == diagnostics.FINGERPRINTS
    assert audit["formal_OOS_orchestrator_sha256"] == (
        diagnostics.OOS_ORCHESTRATOR_SHA
    )
    assert audit["formal_OOS_gate_passed"] is True
    assert all(not value for value in audit["failure_sets"].values())
    assert audit["evidence_counts"] == {
        "formal_mechanism_source_runs": 10,
        "formal_OOS_primary_runs": 10,
        "strategy_plan_identities": 50,
        "exact_recourse_evaluations": 100000,
        "scenario_generations": 0,
        "gurobi_calls": 0,
        "new_scientific_experiments": 0,
        "new_confirmatory_statistics": 0,
        "M2_1_runs": 0,
        "algorithm_performance_runs": 0,
        "M0_E3_runs": 0,
    }


def test_csv_and_audit_rows_recompute_from_pr58_and_pr60() -> None:
    expected_rows, context = diagnostics.build_rows(ROOT)
    expected_summary = diagnostics.build_summary(expected_rows, context)
    audit = load_audit()
    with CSV_PATH.open(encoding="utf-8", newline="") as stream:
        observed_rows = [
            normalize_csv_row(row) for row in csv.DictReader(stream)
        ]
    assert observed_rows == expected_rows == audit["seed_rows"]
    assert expected_summary == audit["summary"]
    assert len(observed_rows) == 10
    assert {row["training_seed"] for row in observed_rows} == set(
        range(2026081401, 2026081411)
    )
    assert len({row["oos_run_id"] for row in observed_rows}) == 10
    assert len({row["source_mechanism_run_id"] for row in observed_rows}) == 10
    assert diagnostics.canonical_sha256(
        {str(row["training_seed"]): row for row in expected_rows}
    ) == audit["seed_row_mapping_sha256"]


def test_activation_thresholds_and_mean_are_original_frozen_values() -> None:
    audit = load_audit()
    assert audit["frozen_activation_thresholds"] == {
        "numerical_strictly_greater_than": 1e-4,
        "substantive_greater_than_or_equal_to": 0.01,
        "moderate_inclusive_range": [0.05, 0.50],
    }
    rows = audit["seed_rows"]
    for row in rows:
        ratio = row["endogenous_reserve_amount"] / row["budget"]
        assert math.isclose(
            ratio, row["endogenous_reserve_ratio"], abs_tol=1e-15
        )
        assert row["numerical_activation"] is (ratio > 1e-4)
        assert row["substantive_activation"] is (ratio >= 0.01)
        assert row["moderate_activation"] is (
            ratio >= 0.01 and 0.05 <= ratio <= 0.50
        )
        assert math.isclose(
            row["fixed_10_reserve_amount"], 0.1 * row["budget"], abs_tol=1e-9
        )
        assert math.isclose(
            row["fixed_30_reserve_amount"], 0.3 * row["budget"], abs_tol=1e-9
        )
        assert math.isclose(
            row["fixed_50_reserve_amount"], 0.5 * row["budget"], abs_tol=1e-9
        )
    activation = audit["summary"]["activation"]
    assert activation["zero_endogenous_reserve_seed_count"] == 4
    assert activation["positive_endogenous_reserve_seed_count"] == 6
    assert activation["substantive_activation_seed_count"] == 6
    assert activation["moderate_activation_seed_count"] == 5
    assert math.isclose(
        activation["reserve_ratio"]["mean"],
        0.06253933410573335,
        abs_tol=1e-15,
    )


def test_training_selection_never_uses_oos_metrics() -> None:
    audit = load_audit()
    pr60 = json.loads((ROOT / diagnostics.PR60_REL).read_text(encoding="utf-8"))
    by_seed = {row["training_seed"]: row for row in pr60["runs"]}
    selection_counts = {name: 0 for name, _ in diagnostics.FIXED}
    for observed in audit["seed_rows"]:
        source = by_seed[observed["training_seed"]]["strategy_results"]
        selected = min(
            diagnostics.FIXED,
            key=lambda pair: (
                source[pair[0]]["source_plan_identity"][
                    "exact_training_objective"
                ],
                pair[1],
            ),
        )[0]
        assert observed["training_selected_best_fixed_strategy"] == selected
        selection_counts[selected] += 1
    assert selection_counts == {
        "fixed_autonomous_reserve_0_10": 9,
        "fixed_autonomous_reserve_0_30": 1,
        "fixed_autonomous_reserve_0_50": 0,
    }
    ranking = audit["summary"]["ranking"]
    assert ranking["top_strategy_reversal_count_for_oos_mean"] == 10
    assert ranking["top_strategy_reversal_count_for_oos_cvar"] == 10
    assert ranking["top_strategy_reversal_count_for_oos_service"] == 10
    assert ranking[
        "endogenous_worse_than_training_selected_fixed_on_oos_mean_count"
    ] == 8
    assert ranking[
        "endogenous_worse_than_training_selected_fixed_on_oos_cvar_count"
    ] == 8


def test_report_is_descriptive_and_monetary_decomposition_is_bounded() -> None:
    report = REPORT_PATH.read_text(encoding="utf-8")
    audit = load_audit()
    assert diagnostics.DIAGNOSTIC_KIND in report
    assert diagnostics.FINAL_STATUS in report
    assert "与……一致" in report
    assert "提示可能存在" in report
    assert "当前证据不足以证明" in report
    assert "证明由……导致" not in report
    decomposition = audit["summary"]["monetary_component_decomposition"]
    assert decomposition["status"] == (
        "retained_artifacts_do_not_support_exact_monetary_component_"
        "decomposition"
    )
    assert decomposition["residual_subtraction_used"] is False
    assert audit["summary"]["final_status"] == diagnostics.FINAL_STATUS
    assert audit["final_status"] == diagnostics.FINAL_STATUS
    assert audit["stop_boundary"] == {
        "M2_1_development_authorized": False,
        "M2_1_execution_authorized": False,
        "algorithm_performance_authorized": False,
        "M0_E3_authorized": False,
        "next_action": "review_this_draft_PR_only",
    }


def test_generated_artifact_hashes_are_exact() -> None:
    audit = load_audit()
    generated = audit["generated_artifacts"]
    assert generated["csv_sha256"] == sha256(CSV_PATH)
    assert generated["report_sha256"] == sha256(REPORT_PATH)
    assert generated["script_sha256"] == sha256(SCRIPT_PATH)


def test_script_has_no_solver_scenario_or_formal_output_write_path(
    tmp_path: Path,
) -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (
            node.names if isinstance(node, ast.Import)
            else [ast.alias(name=node.module or "")]
        )
    }
    assert imports.isdisjoint({
        "gurobipy", "pyomo", "phase6_m2", "scenario_generation",
        "extensive_model", "recourse_model",
    })
    for forbidden in (
        "SolverFactory", "generate_phase6_data", "generate_m2_data",
        "solve_m1", "solve_m2", "run_phase6",
    ):
        assert forbidden not in source
    with pytest.raises(diagnostics.DiagnosticError):
        diagnostics.write_outputs(ROOT, tmp_path)
