from __future__ import annotations

import hashlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pytest
import yaml

import src.phase6_m2c2_confirmation as runner
from src.phase6_m2 import (
    _fulfillment_rates,
    reconstruct_frozen_demand_latent,
    resolve_supply_disruption_profile,
)
from src.phase6_protocol import generate_phase6_data, load_phase6_matrix


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/phase6_m2_two_item_confirmation.yaml"
RUNNER = ROOT / "configs/phase6_m2c2_confirmation_runner.yaml"
APPROVAL = ROOT / "configs/phase6_m2c2_confirmation_approval.yaml"
FINGERPRINTS = {
    "scientific_config_sha256": "1" * 64,
    "e3_component_sha256": "2" * 64,
    "family_component_sha256": "3" * 64,
    "runner_config_sha256": "4" * 64,
    "environment_sha256": "5" * 64,
}


def _registry_process(output_root: str, index: int) -> str:
    row = {field: "" for field in runner.REGISTRY_FIELDS}
    row.update({
        "run_id": f"concurrent-{index}",
        "case_id": f"case-{index}",
        "status": "optimal",
    })
    runner._write_registry(Path(output_root), row)
    return row["run_id"]


def _science(case: runner.ConfirmationCase) -> dict[str, Any]:
    ratio = 0.10 if case.profile_id == "T03" else 0.0
    budget = 100.0 * case.beta
    shared = {
        name: hashlib.sha256(f"{name}-{case.seed}-{case.beta}".encode()).hexdigest()
        for name in (
            "latent_draw_sha256", "demand_sha256", "emergency_price_sha256",
            "emergency_supply_sha256", "scenario_order_sha256",
        )
    }
    shared["fulfillment_sha256"] = hashlib.sha256(
        f"fulfillment-{case.profile_id}-{case.seed}-{case.beta}".encode()
    ).hexdigest()
    return {
        "profile_id": case.profile_id,
        "budget": budget,
        "R_min_feas": 0.0,
        "R_min_opt": ratio * budget,
        "R_max_opt": ratio * budget,
        "R_min_robust_opt": ratio * budget,
        "R_min_robust_opt_ratio": ratio,
        "numerical_activation": ratio > 1e-4,
        "substantive_activation": ratio >= 0.01,
        "objective_tolerance": 1e-5,
        "complete_extensive_objective": 100.0,
        "minimum_endpoint_status": "optimal",
        "maximum_endpoint_status": "optimal",
        "minimum_endpoint_exact_objective": 100.0,
        "maximum_endpoint_exact_objective": 100.0,
        "endpoint_failure_counts": {
            "minimum": {"infeasible": 0, "solver_failure": 0, "missing": 0},
            "maximum": {"infeasible": 0, "solver_failure": 0, "missing": 0},
        },
        "fixed_reserve_policies": [
            {
                "rho": rho, "status": "optimal",
                "reserve": rho * budget,
                "regular_purchase_sha256": hashlib.sha256(
                    f"purchase-{case.case_id}-{rho}".encode()
                ).hexdigest(),
                "regular_purchase_reoptimized": True,
            }
            for rho in (0.0, 0.1, 0.3, 0.5)
        ],
        "scenario_component_set_sha256": shared,
        "cross_item_allocation": {
            "plan_source": "complete_extensive_model_R_min_opt_endpoint",
            "scenario_count": 50,
            "scenario_item_emergency_spend": {
                f"s{index:04d}": {
                    "relief_food_1": (1.0 + index if case.profile_id == "T03" else 0.0),
                    "relief_food_2": (50.0 - index if case.profile_id == "T03" else 0.0),
                    "total": (51.0 if case.profile_id == "T03" else 0.0),
                }
                for index in range(50)
            },
        },
        "c0_equivalence": {
            "required": case.profile_id == "C0",
            "status": "passed" if case.profile_id == "C0" else "not_applicable",
            "robust_objective_difference": 0.0,
            "reserve_interval_endpoint_differences": {"minimum": 0.0, "maximum": 0.0},
            "M2C0_plan_evaluated_in_no_disruption_max_scenario_cost_difference": 0.0,
            "no_disruption_plan_evaluated_in_M2C0_max_scenario_cost_difference": 0.0,
            "fulfillment_exactly_one": case.profile_id == "C0",
            "scenario_count_each_direction": 50 if case.profile_id == "C0" else 0,
        },
    }


def _results(config: dict[str, Any]) -> list[tuple[dict[str, str], dict[str, Any]]]:
    values = []
    for case in runner.build_confirmation_cases(config):
        run_id = f"primary_{case.case_id}"
        row = {field: "" for field in runner.REGISTRY_FIELDS}
        row.update({
            "run_id": run_id, "case_id": case.case_id,
            "seed": str(case.seed), "beta": str(case.beta),
            "profile_id": case.profile_id, "status": "optimal",
            **FINGERPRINTS,
        })
        result = {
            "run_id": run_id, "case_id": case.case_id,
            "case": case.as_dict(), "status": "optimal", "finalized": True,
            "science": _science(case), "fingerprints": FINGERPRINTS,
        }
        values.append((row, result))
    return values


def test_exact_30_case_cartesian_product_and_identity() -> None:
    config = runner.load_confirmation_config(CONFIG)
    cases = runner.build_confirmation_cases(config)
    assert len(cases) == len({case.case_id for case in cases}) == 30
    assert {(case.seed, case.beta, case.profile_id) for case in cases} == {
        (seed, beta, profile)
        for seed in (2026081301, 2026081302, 2026081303, 2026081304, 2026081305)
        for beta in (1.1, 1.3)
        for profile in ("C0", "C1", "T03")
    }
    assert all(case.tier_id == "M2C2" for case in cases)
    assert config["status"] == runner.READY_STATUS


def test_reference_budget_capacity_and_distinct_M2C2_tier_recompute() -> None:
    config = runner.load_confirmation_config(CONFIG)
    matrix = runner.load_phase6_matrix(ROOT / "configs/phase6_experiment_matrix.yaml")
    baseline = runner._validate_m2c2_baseline(matrix, config)
    assert baseline["reference_budget"] == pytest.approx(2337.610924158743, abs=1e-9)
    assert baseline["budgets"] == pytest.approx({
        "1.1": 2571.372016574617,
        "1.3": 3038.894201406366,
    }, abs=1e-9)
    resolved = runner._m2c2_matrix(matrix, config)
    assert runner.resolve_tier(resolved, "M2C2").items == 2
    assert resolved["budget_plan"]["reference_budget_by_tier"]["M2C2"] != resolved["budget_plan"]["reference_budget_by_tier"]["V1"]


def test_optional_vulnerability_defaults_to_legacy_M2_and_changes_only_fulfillment() -> None:
    config = runner.load_confirmation_config(CONFIG)
    matrix = load_phase6_matrix(ROOT / "configs/phase6_experiment_matrix.yaml")
    resolved = runner._m2c2_matrix(matrix, config)
    generated = generate_phase6_data(
        resolved,
        matrix_path=ROOT / "configs/phase6_experiment_matrix.yaml",
        tier_id="M2C2",
        seed=2026081301,
        budget=2571.372016574617,
    )
    latent = reconstruct_frozen_demand_latent(resolved, generated)
    profile = resolve_supply_disruption_profile(
        runner._science_config(ROOT, config), "T03"
    )
    legacy = _fulfillment_rates(generated, profile, latent)
    explicit_one = runner.apply_m2c2_supply_disruption(
        generated,
        profile=profile,
        demand_latent=latent,
        item_vulnerability_multiplier={item: 1.0 for item in generated.data.items},
    ).data.regular_fulfillment_rate
    heterogeneous = runner.apply_m2c2_supply_disruption(
        generated,
        profile=profile,
        demand_latent=latent,
        item_vulnerability_multiplier={"relief_food_1": 0.8, "relief_food_2": 1.2},
    ).data.regular_fulfillment_rate
    assert legacy == explicit_one
    assert heterogeneous != legacy
    assert all(
        heterogeneous[scenario]["relief_food_1"][period]
        > legacy[scenario]["relief_food_1"][period]
        and heterogeneous[scenario]["relief_food_2"][period]
        < legacy[scenario]["relief_food_2"][period]
        for scenario in generated.data.scenarios
        for period in range(generated.data.periods)
    )
    # Both calls consume the same already-generated data and latent mapping;
    # the helper performs no RNG operation and returns only fulfillment rates.
    assert set(heterogeneous) == set(generated.data.scenarios)


def test_preflight_rejects_missing_authorization_before_environment(monkeypatch) -> None:
    monkeypatch.setattr(
        runner, "validate_locked_environment",
        lambda *_: pytest.fail("environment validation reached"),
    )
    with pytest.raises(PermissionError):
        runner.validate_preflight(
            root=ROOT, config_path=CONFIG, runner_path=RUNNER,
            approval_path=APPROVAL, authorize=False,
        )


def test_approval_locks_current_fingerprints_and_zero_execution_counts() -> None:
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    actual = runner.confirmation_fingerprints(ROOT, CONFIG, RUNNER)
    approved = approval["approved_fingerprints"]
    for field in runner.FINGERPRINT_FIELDS[:-1]:
        assert approved[field] == actual[field]
    # Linux CI deliberately has a different platform/hardware identity. The
    # runtime preflight still compares all five approved fields strictly.
    assert approved["environment_sha256"] == (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    )
    assert approval["matrix_case_count"] == 30
    assert approval["formal_extension_authorized"] is False
    assert approval["accept_prior_track_authorization"] is False
    assert set(approval["execution_counts_in_this_revision"].values()) == {0}


def test_prior_track_approval_cannot_authorize_M2C2(tmp_path, monkeypatch) -> None:
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    approval["accept_prior_track_authorization"] = True
    path = tmp_path / "approval.yaml"
    path.write_text(yaml.safe_dump(approval), encoding="utf-8")
    monkeypatch.setattr(
        runner, "validate_locked_environment",
        lambda *_: pytest.fail("environment validation reached"),
    )
    with pytest.raises(RuntimeError, match="approval metadata mismatch"):
        runner.validate_preflight(
            root=ROOT, config_path=CONFIG, runner_path=RUNNER,
            approval_path=path, authorize=True,
        )


def test_projection_recomputes_all_gates_and_claim_scope(monkeypatch, tmp_path) -> None:
    config = runner.load_confirmation_config(CONFIG)
    evidence = _results(config)
    monkeypatch.setattr(runner, "_read_registry", lambda _path: [row for row, _ in evidence])
    by_id = {row["run_id"]: result for row, result in evidence}
    monkeypatch.setattr(runner, "_validate_artifact", lambda row: by_id[row["run_id"]])
    projection = runner.update_projection(
        output_root=tmp_path, config=config, fingerprints=FINGERPRINTS,
    )
    assert projection["status"] == "complete"
    assert projection["verified_primary_run_count"] == 30
    assert projection["passing_betas"] == [1.1, 1.3]
    assert projection["claim_scope"] == "both_betas_budget_moderation_comparison_allowed"
    assert projection["overall_decision"] == "permit_separate_formal_extension_design_PR_only"
    assert projection["formal_extension_authorized"] is False
    assert all(item["C0_equivalence_seed_count"] == 5 for item in projection["beta_assessments"])
    assert all(item["T03_cross_item_gate_seed_count"] == 5 for item in projection["beta_assessments"])


def test_crn_mismatch_blocks_confirmation(monkeypatch, tmp_path) -> None:
    config = runner.load_confirmation_config(CONFIG)
    evidence = _results(config)
    target = next(
        result for _, result in evidence
        if result["case"]["seed"] == 2026081301
        and result["case"]["beta"] == 1.1
        and result["case"]["profile_id"] == "T03"
    )
    target["science"]["scenario_component_set_sha256"]["demand_sha256"] = "f" * 64
    monkeypatch.setattr(runner, "_read_registry", lambda _path: [row for row, _ in evidence])
    by_id = {row["run_id"]: result for row, result in evidence}
    monkeypatch.setattr(runner, "_validate_artifact", lambda row: by_id[row["run_id"]])
    projection = runner.update_projection(
        output_root=tmp_path, config=config, fingerprints=FINGERPRINTS,
    )
    beta = next(item for item in projection["beta_assessments"] if item["beta"] == 1.1)
    assert beta["common_random_numbers_verified"] is False
    assert beta["confirmation_gate_passed"] is False


def test_scenario_order_mismatch_blocks_confirmation(monkeypatch, tmp_path) -> None:
    config = runner.load_confirmation_config(CONFIG)
    evidence = _results(config)
    target = next(
        result for _, result in evidence
        if result["case"]["seed"] == 2026081301
        and result["case"]["beta"] == 1.1
        and result["case"]["profile_id"] == "T03"
    )
    target["science"]["scenario_component_set_sha256"]["scenario_order_sha256"] = "f" * 64
    monkeypatch.setattr(runner, "_read_registry", lambda _path: [row for row, _ in evidence])
    by_id = {row["run_id"]: result for row, result in evidence}
    monkeypatch.setattr(runner, "_validate_artifact", lambda row: by_id[row["run_id"]])
    projection = runner.update_projection(
        output_root=tmp_path, config=config, fingerprints=FINGERPRINTS,
    )
    beta = next(item for item in projection["beta_assessments"] if item["beta"] == 1.1)
    assert beta["common_random_numbers_verified"] is False
    assert beta["confirmation_gate_passed"] is False


def test_fixed_autonomous_reserve_formula_is_recomputed() -> None:
    config = runner.load_confirmation_config(CONFIG)
    case = runner.build_confirmation_cases(config)[0]
    science = _science(case)
    science["fixed_reserve_policies"][1]["reserve"] += 1.0
    with pytest.raises(ValueError, match="fixed autonomous reserve formula"):
        runner._derive_science(science, config)


def test_one_passing_beta_forbids_budget_effect_claim(monkeypatch, tmp_path) -> None:
    config = runner.load_confirmation_config(CONFIG)
    evidence = _results(config)
    for _, result in evidence:
        case = result["case"]
        if case["beta"] == 1.3 and case["profile_id"] == "T03":
            science = result["science"]
            science["R_min_opt"] = science["R_min_feas"]
            science["R_min_robust_opt"] = 0.0
            science["R_min_robust_opt_ratio"] = 0.0
            science["numerical_activation"] = False
            science["substantive_activation"] = False
    monkeypatch.setattr(runner, "_read_registry", lambda _path: [row for row, _ in evidence])
    by_id = {row["run_id"]: result for row, result in evidence}
    monkeypatch.setattr(runner, "_validate_artifact", lambda row: by_id[row["run_id"]])
    projection = runner.update_projection(
        output_root=tmp_path, config=config, fingerprints=FINGERPRINTS,
    )
    assert projection["passing_betas"] == [1.1]
    assert projection["claim_scope"] == "single_beta_only_budget_effect_claims_forbidden"


def test_primary_requires_full_matrix_and_stops_after_failure(monkeypatch, tmp_path) -> None:
    config = runner.load_confirmation_config(CONFIG)
    cases = runner.build_confirmation_cases(config)
    monkeypatch.setattr(runner, "OUTPUT_ROOT", str(tmp_path))
    monkeypatch.setattr(runner, "validate_preflight", lambda **_: {
        "config": config, "fingerprints": FINGERPRINTS,
        "locked_environment": {}, "source": {"commit_sha": "a" * 40, "tree_sha": "b" * 40},
    })
    calls = []
    def fake_run_case(**kwargs):
        calls.append(kwargs["case"].case_id)
        return {"status": "stage_failure"}
    monkeypatch.setattr(runner, "run_case", fake_run_case)
    with pytest.raises(ValueError, match="complete frozen 30-case"):
        runner.run_matrix(
            root=ROOT, config_path=CONFIG, runner_path=RUNNER,
            approval_path=APPROVAL, authorize=True, run_id_prefix="partial",
            case_ids=[cases[0].case_id],
        )
    rows = runner.run_matrix(
        root=ROOT, config_path=CONFIG, runner_path=RUNNER,
        approval_path=APPROVAL, authorize=True, run_id_prefix="stop",
    )
    assert len(rows) == len(calls) == 1


def test_failed_run_id_is_immutable_and_status_is_bounded(tmp_path, monkeypatch) -> None:
    config = runner.load_confirmation_config(CONFIG)
    case = runner.build_confirmation_cases(config)[0]
    monkeypatch.setattr(runner, "capture_runtime_context", lambda **_: {})
    def fail(**_):
        raise RuntimeError("failed")
    result = runner.run_case(
        root=ROOT, output_root=tmp_path,
        matrix_path=ROOT / "configs/phase6_experiment_matrix.yaml",
        config=config, fingerprints=FINGERPRINTS,
        locked_environment={}, source={"commit_sha": "a" * 40, "tree_sha": "b" * 40},
        case=case, run_id="immutable", science_executor=fail,
    )
    assert result["status"] == "stage_failure"
    with pytest.raises(ValueError, match="immutable"):
        runner.run_case(
            root=ROOT, output_root=tmp_path,
            matrix_path=ROOT / "configs/phase6_experiment_matrix.yaml",
            config=config, fingerprints=FINGERPRINTS,
            locked_environment={}, source={"commit_sha": "a" * 40, "tree_sha": "b" * 40},
            case=case, run_id="immutable", science_executor=fail,
        )
    assert (tmp_path / "confirmation/runs/immutable/status_summary.json").stat().st_size < 16 * 1024


def test_cross_process_registry_writes_preserve_all_rows(tmp_path) -> None:
    with ProcessPoolExecutor(max_workers=4) as pool:
        run_ids = list(pool.map(_registry_process, [str(tmp_path)] * 20, range(20)))
    rows = runner._read_registry(tmp_path / "confirmation/confirmation_run_registry.csv")
    assert {row["run_id"] for row in rows} == set(run_ids)


@pytest.mark.parametrize("failure_point", ["runtime_context", "manifest", "registry", "projection"])
def test_finalization_failure_leaves_bounded_terminal_diagnostic(
    tmp_path, monkeypatch, failure_point
) -> None:
    config = runner.load_confirmation_config(CONFIG)
    case = runner.build_confirmation_cases(config)[0]
    original_write = runner.atomic_write_json
    monkeypatch.setattr(
        runner, "capture_runtime_context",
        lambda **_: (
            (_ for _ in ()).throw(RuntimeError("x" * 20000))
            if failure_point == "runtime_context" else {}
        ),
    )
    if failure_point == "manifest":
        monkeypatch.setattr(
            runner, "atomic_write_json",
            lambda path, payload: (
                (_ for _ in ()).throw(PermissionError("manifest locked"))
                if Path(path).name == "manifest.json"
                else original_write(path, payload)
            ),
        )
    if failure_point == "registry":
        monkeypatch.setattr(
            runner, "_write_registry",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("registry locked")),
        )
    if failure_point == "projection":
        monkeypatch.setattr(
            runner, "update_projection",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("projection failed")),
        )
    with pytest.raises((RuntimeError, PermissionError)):
        runner.run_case(
            root=ROOT, output_root=tmp_path,
            matrix_path=ROOT / "configs/phase6_experiment_matrix.yaml",
            config=config, fingerprints=FINGERPRINTS,
            locked_environment={}, source={"commit_sha": "a" * 40, "tree_sha": "b" * 40},
            case=case, run_id=f"final-{failure_point}",
            science_executor=lambda **_: _science(case),
        )
    directory = tmp_path / "confirmation/runs" / f"final-{failure_point}"
    status = directory / "status_summary.json"
    assert status.is_file() and status.stat().st_size < 16 * 1024
