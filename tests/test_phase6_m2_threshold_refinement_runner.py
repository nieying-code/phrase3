from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pytest
import yaml

import src.phase6_m2_threshold_refinement as runner
from src.phase6_io import atomic_write_json
from src.reproducibility import sha256_file


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/phase6_m2_threshold_refinement.yaml"
RUNNER = ROOT / "configs/phase6_m2_threshold_refinement_runner.yaml"
APPROVAL = ROOT / "configs/phase6_m2_threshold_refinement_approval.yaml"
FINGERPRINTS = {
    "scientific_config_sha256": "1"*64, "e3_component_sha256": "2"*64,
    "family_component_sha256": "3"*64, "runner_config_sha256": "4"*64,
    "environment_sha256": "5"*64,
}


def _registry_process(output_root: str, index: int) -> str:
    row={field:"" for field in runner.REGISTRY_FIELDS}
    row.update({"run_id":f"concurrent-{index}","case_id":f"case-{index}","status":"optimal"})
    runner._write_registry(Path(output_root),row)
    return row["run_id"]


def _science(*, case, progress, **_kwargs) -> dict[str, Any]:
    progress("scenario_generation", {})
    budget = case.beta * 100.0
    ratio = {"T03": 0.0, "T04": 0.1, "T05": 0.2}[case.profile_id]
    hashes = {
        name: runner.hashlib.sha256(f"{name}-{case.seed}-{case.beta}".encode()).hexdigest()
        for name in ("latent_draw_sha256", "demand_sha256", "emergency_price_sha256", "emergency_supply_sha256")
    }
    hashes["fulfillment_sha256"] = runner.hashlib.sha256(f"fulfillment-{case.profile_id}".encode()).hexdigest()
    return {
        "budget": budget, "R_min_feas": 0.0, "R_min_opt": ratio*budget,
        "R_max_opt": ratio*budget+1e-8, "R_min_robust_opt": ratio*budget,
        "R_min_robust_opt_ratio": ratio, "numerical_activation": ratio > 1e-4,
        "substantive_activation": ratio >= .01, "objective_tolerance": 1e-5,
        "complete_extensive_objective": 100.0,
        "minimum_endpoint_status": "optimal", "maximum_endpoint_status": "optimal",
        "minimum_endpoint_exact_objective": 100.0, "maximum_endpoint_exact_objective": 100.0,
        "endpoint_failure_counts": {"minimum":{"infeasible":0,"solver_failure":0,"missing":0},"maximum":{"infeasible":0,"solver_failure":0,"missing":0}},
        "fixed_reserve_policies": [
            {"rho":rho,"status":"optimal","regular_purchase_reoptimized":True,"regular_purchase_sha256":str(i+1)*64}
            for i,rho in enumerate((0.0,0.1,0.3,0.5))
        ],
        "scenario_component_set_sha256": hashes,
    }


def _anchor(seed: int, beta: float, profile: str, active: bool) -> dict[str, Any]:
    return {
        "seed":seed,"beta":beta,"profile_id":profile,"status":"optimal",
        "substantive_activation":active,
        "scenario_component_set_sha256": {
            name: runner.hashlib.sha256(f"{name}-{seed}-{beta}".encode()).hexdigest()
            for name in ("latent_draw_sha256","demand_sha256","emergency_price_sha256","emergency_supply_sha256")
        } | {"fulfillment_sha256": runner.hashlib.sha256(f"fulfillment-{profile}".encode()).hexdigest()},
    }


def _anchors() -> dict[tuple[int,float,str],dict[str,Any]]:
    return {(seed,beta,profile):_anchor(seed,beta,profile,profile=="C2")
            for seed in (2026081201,2026081202,2026081203)
            for beta in (0.9,1.1,1.3) for profile in ("C1","C2")}


def _populate(output: Path, config: dict[str, Any], profile_ratios: dict[str,float] | None = None) -> None:
    profile_ratios = profile_ratios or {"T03":0.0,"T04":0.1,"T05":0.2}
    for case in runner.build_refinement_cases(config):
        run_id=f"test_{case.case_id}"; directory=output/"development/runs"/run_id; directory.mkdir(parents=True)
        science=_science(case=case,progress=lambda *_:None)
        ratio=profile_ratios[case.profile_id]; science["R_min_opt"]=ratio*science["budget"]
        science["R_min_robust_opt"]=ratio*science["budget"]; science["R_min_robust_opt_ratio"]=ratio
        science["numerical_activation"]=ratio>1e-4; science["substantive_activation"]=ratio>=.01
        result={"run_id":run_id,"case_id":case.case_id,"case":case.as_dict(),"status":"optimal","finalized":True,"science":science,"fingerprints":FINGERPRINTS}
        result_path=directory/"result.json"; manifest_path=directory/"manifest.json"
        atomic_write_json(result_path,result); atomic_write_json(manifest_path,{"result_sha256":sha256_file(result_path),"fingerprints":FINGERPRINTS})
        row={field:"" for field in runner.REGISTRY_FIELDS}; row.update({"run_id":run_id,"case_id":case.case_id,"seed":case.seed,"beta":case.beta,"profile_id":case.profile_id,"status":"optimal",**FINGERPRINTS,"result_path":str(result_path),"manifest_path":str(manifest_path),"manifest_sha256":sha256_file(manifest_path)})
        runner._write_registry(output,row)


def test_exact_27_case_cartesian_product_and_frozen_identity() -> None:
    config=runner.load_refinement_config(CONFIG); cases=runner.build_refinement_cases(config)
    assert len(cases)==len({c.case_id for c in cases})==27
    assert {(c.seed,c.beta,c.profile_id) for c in cases} == {
        (seed,beta,profile) for seed in (2026081201,2026081202,2026081203)
        for beta in (0.9,1.1,1.3) for profile in ("T03","T04","T05")
    }
    assert config["status"]==runner.READY_STATUS
    assert yaml.safe_load(APPROVAL.read_text())["formal_extension_authorized"] is False


def test_preflight_rejects_missing_authorization_and_candidate_before_environment(monkeypatch,tmp_path) -> None:
    monkeypatch.setattr(runner,"validate_locked_environment",lambda *_:pytest.fail("environment reached"))
    with pytest.raises(PermissionError): runner.validate_preflight(root=ROOT,config_path=CONFIG,runner_path=RUNNER,approval_path=APPROVAL,authorize=False)
    candidate=tmp_path/"candidate.yaml"; candidate.write_text(CONFIG.read_text().replace(runner.READY_STATUS,"candidate_design_pending_review"),encoding="utf-8")
    with pytest.raises(RuntimeError,match="not frozen"): runner.validate_preflight(root=ROOT,config_path=candidate,runner_path=RUNNER,approval_path=APPROVAL,authorize=True)


def test_parent_anchor_hash_and_per_beta_evidence_are_enforced(tmp_path) -> None:
    config=runner.load_refinement_config(CONFIG)
    anchors=runner.load_parent_anchors(ROOT,config["parent_protocol"]["results_audit_sha256"])
    assert len(anchors)==18
    for beta in (0.9,1.1,1.3):
        assert sum(anchors[(s,beta,"C1")]["substantive_activation"] for s in (2026081201,2026081202,2026081203))==0
        assert sum(anchors[(s,beta,"C2")]["substantive_activation"] for s in (2026081201,2026081202,2026081203))==3
    with pytest.raises(ValueError,match="hash mismatch"): runner.load_parent_anchors(ROOT,"0"*64)


def test_projection_recomputes_activation_moderate_gate_crn_and_per_beta_brackets(tmp_path) -> None:
    config=runner.load_refinement_config(CONFIG); _populate(tmp_path,config)
    projection=runner.update_projection(output_root=tmp_path,config=config,fingerprints=FINGERPRINTS,anchors=_anchors())
    assert projection["verified_primary_run_count"]==27
    assert projection["formal_extension_authorized"] is False
    assert all(item["activation_sequence"]==[False,False,True,True,True] for item in projection["beta_assessments"])
    assert all(item["threshold_bracket"]=={"lower_profile":"T03","upper_profile":"T04","lower_loss_scale":.3,"upper_loss_scale":.4} for item in projection["beta_assessments"])
    assert all(item["common_random_numbers_verified"] for item in projection["beta_assessments"])
    t04=[x for x in projection["combinations"] if x["profile_id"]=="T04"]
    assert all(item["combination_activation_gate_passed"] and item["moderate_gate_passed"] for item in t04)


def test_nonmonotone_pattern_blocks_beta_bracket_and_candidate(tmp_path) -> None:
    config=runner.load_refinement_config(CONFIG); _populate(tmp_path,config,{"T03":.1,"T04":0.0,"T05":.2})
    projection=runner.update_projection(output_root=tmp_path,config=config,fingerprints=FINGERPRINTS,anchors=_anchors())
    assert all(item["status"]=="nonmonotone_activation_pattern" for item in projection["beta_assessments"])
    assert all(item["threshold_bracket"] is None and not item["multi_item_candidate_allowed"] for item in projection["beta_assessments"])


def test_moderate_count_cannot_pass_without_combination_activation(tmp_path) -> None:
    config=runner.load_refinement_config(CONFIG); _populate(tmp_path,config,{"T03":.1,"T04":.1,"T05":.1})
    # Corrupt one T03 result into a scientific failure: only two remain is still activation;
    # corrupt a second by removing registry row, leaving moderate count 1 and no activation.
    path=tmp_path/"development/refinement_run_registry.csv"; rows=runner._read_registry(path)
    kept=[]; removed=0
    for row in rows:
        if row["profile_id"]=="T03" and row["beta"]=="0.9" and removed<2: removed+=1
        else: kept.append(row)
    runner.atomic_write_csv(path,runner.REGISTRY_FIELDS,kept)
    projection=runner.update_projection(output_root=tmp_path,config=config,fingerprints=FINGERPRINTS,anchors=_anchors())
    row=next(x for x in projection["combinations"] if x["beta"]==.9 and x["profile_id"]=="T03")
    assert row["moderate_seed_count"]==1
    assert row["combination_activation_gate_passed"] is False
    assert row["moderate_gate_passed"] is False


def test_run_id_immutability_failure_stop_and_bounded_status(tmp_path,monkeypatch) -> None:
    monkeypatch.setattr(runner,"capture_runtime_context",lambda **_: {})
    config=runner.load_refinement_config(CONFIG); case=runner.build_refinement_cases(config)[0]
    def fail(**_): raise RuntimeError("failed")
    result=runner.run_case(root=ROOT,output_root=tmp_path,matrix_path=ROOT/"configs/phase6_experiment_matrix.yaml",config=config,fingerprints=FINGERPRINTS,anchors=_anchors(),locked_environment={},source={"commit_sha":"a"*40,"tree_sha":"b"*40},case=case,run_id="immutable",science_executor=fail)
    assert result["status"]=="stage_failure"
    with pytest.raises(ValueError,match="immutable"): runner.run_case(root=ROOT,output_root=tmp_path,matrix_path=ROOT/"configs/phase6_experiment_matrix.yaml",config=config,fingerprints=FINGERPRINTS,anchors=_anchors(),locked_environment={},source={"commit_sha":"a"*40,"tree_sha":"b"*40},case=case,run_id="immutable",science_executor=_science)
    status_path=tmp_path/"development/runs/immutable/status_summary.json"
    assert status_path.stat().st_size < 16*1024


def test_cross_process_registry_writes_preserve_all_rows(tmp_path) -> None:
    with ProcessPoolExecutor(max_workers=4) as pool:
        run_ids=list(pool.map(_registry_process,[str(tmp_path)]*20,range(20)))
    rows=runner._read_registry(tmp_path/"development/refinement_run_registry.csv")
    assert {row["run_id"] for row in rows}==set(run_ids)


def test_matrix_stops_after_first_failed_case(monkeypatch,tmp_path) -> None:
    config=runner.load_refinement_config(CONFIG); cases=runner.build_refinement_cases(config)
    monkeypatch.setattr(runner,"validate_preflight",lambda **_:{"config":config,"fingerprints":FINGERPRINTS,"anchors":_anchors(),"locked_environment":{},"source":{"commit_sha":"a"*40,"tree_sha":"b"*40}})
    calls=[]
    def fake_run_case(**kwargs):
        calls.append(kwargs["case"].case_id)
        return {"status":"stage_failure"}
    monkeypatch.setattr(runner,"run_case",fake_run_case)
    rows=runner.run_matrix(root=ROOT,config_path=CONFIG,runner_path=RUNNER,approval_path=APPROVAL,authorize=True,run_id_prefix="stop",case_ids=[cases[0].case_id,cases[1].case_id])
    assert len(rows)==1 and len(calls)==1


def test_preflight_uses_independent_namespace_and_never_accepts_parent_registry() -> None:
    runner_config=yaml.safe_load(RUNNER.read_text())
    assert runner_config["namespace"]==runner.RUNNER_NAMESPACE
    assert runner_config["output_root"]==runner.OUTPUT_ROOT
    assert runner_config["execution"]["parent_registry_or_projection_import_forbidden"] is True
    assert "phase6_m2_supply_disruption_v1_1" not in runner_config["output_root"]
