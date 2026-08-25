from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.phase6_m2_algorithm_performance_formal import (
    FormalCase, _run_formal_sequence, build_formal_cases, read_status,
    run_formal_batch, update_projection, validate_preflight, validate_static_freeze,
)


ROOT=Path(__file__).resolve().parents[1]
RUNNER=ROOT/"configs/phase6_m2_algorithm_performance_formal_runner_v1_0.yaml"
APPROVAL=ROOT/"configs/phase6_m2_algorithm_performance_formal_approval_v1_0.yaml"


def _sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def _fake_worker(calls,fail_at=None):
    def execute(request,timeout,directory):
        calls.append(request)
        if fail_at and len(calls)==fail_at:
            return {"status":"time_limit","solver_status":"time_limit","failure":{"stage":"solver"}}
        scenarios=[f"s{i:04d}" for i in range(100)]
        prior=request.get("previous_state")
        if prior is None: initial=["s0000","s0099"]
        else: initial=list(prior["final_scenario_set"])
        transferred=[] if prior is None else [n for n in initial if n in set(prior["active_scenarios"])|set(prior["historical_adversarial_scenarios"])]
        costs={name:float(i) for i,name in enumerate(scenarios)}
        result={"termination_status":"optimal","converged":True,"objective":1000.0,"lower_bound":1000.0,"upper_bound":1000.0,"gap":0.0,"iterations":1,"initial_scenario_set":initial,"final_scenario_set":initial,"regular_purchase":{},"reserve":1.0,"reserve_ratio":0.1,"worst_scenario":"s0099","exact_scenario_costs":costs,"total_runtime_seconds":1.0,"master_runtime_seconds":0.2,"oracle_runtime_seconds":0.8,"solver":"gurobi_direct","iteration_log":[],"incumbent_evaluation":{},"joint_scenario_set_sha256":"a"*64,"scenario_identities":[]}
        components={"latent_draw_sha256":"1"*64,"demand_sha256":"2"*64,"fulfillment_sha256":("3" if request["profile_id"]=="C0" else "4")*64,"emergency_price_sha256":"5"*64,"emergency_supply_sha256":"6"*64,"scenario_order_sha256":_sha(scenarios)}
        return {"status":"optimal","solver_status":"optimal","algorithm":request["algorithm"],"repetition":request["repetition"],"objective":1000.0,"scenario_count":100,"joint_scenario_set_sha256":"a"*64,"component_set_sha256":components,"initial_scenarios":initial,"initial_scenario_pool_size":len(initial),"transfer_source_state_sha256":None if prior is None else _sha(prior),"transfer_source_budget":None if prior is None else prior["budget"],"transferred_exact_scenarios":transferred,"transferred_exact_scenario_count":len(transferred),"transferred_scenario_reuse_rate":0.0 if prior is None else len(transferred)/len(initial),"transferred_scenarios_becoming_active_or_worst":[n for n in transferred if n=="s0099"],"transferred_scenarios_becoming_active_or_worst_count":sum(n=="s0099" for n in transferred),"ccg_result":result,"scientific_result":result,"subprocess_wall_seconds":1.0,"sampled_peak_RSS_MiB":10.0,"failure":None}
    return execute


def _context(tmp_path):
    static=validate_static_freeze(ROOT,RUNNER,APPROVAL)
    static.update(fingerprints={"x":"y"},synchronized_main={"head":"1"*40},matrix={})
    return static


def test_frozen_formal_matrix_is_exact_and_pending() -> None:
    context=validate_static_freeze(ROOT,RUNNER,APPROVAL)
    cases=build_formal_cases(context["design"])
    assert len(cases)==20
    assert [(c.seed,c.profile_id) for c in cases]==[(s,p) for s in range(2026091101,2026091111) for p in ("C0","T03")]
    assert context["runner"]["execution"]["algorithm_execution_count"]==240
    assert context["approval"]["formal_authorized"] is True
    assert not (ROOT/context["runner"]["output_root"]).exists()


def test_read_only_preflight_does_not_call_gurobi(monkeypatch) -> None:
    called=False
    def forbidden():
        nonlocal called; called=True; raise AssertionError
    monkeypatch.setattr("src.phase6_m2_algorithm_performance_formal.validate_gurobi_runtime",forbidden)
    monkeypatch.setattr("src.phase6_m2_algorithm_performance_formal.validate_execution_source",lambda *args,**kwargs:{})
    context=validate_preflight(ROOT,RUNNER,APPROVAL,require_authorization=False)
    assert len(context["cases"])==20 and called is False


def test_explicit_cli_authorization_is_required_before_preflight(tmp_path) -> None:
    with pytest.raises(RuntimeError,match="explicit formal"):
        run_formal_batch(
            root=ROOT,runner_path=RUNNER,approval_path=APPROVAL,
            authorize=False,run_id_prefix="forbidden",
        )


def test_one_formal_sequence_has_12_fresh_solves_and_three_transfer_chains(tmp_path) -> None:
    calls=[]; context=_context(tmp_path); case=FormalCase("case",2026091101,"T03")
    result=_run_formal_sequence(root=ROOT,context=context,case=case,run_id="formal_case",execution_root=tmp_path,worker_executor=_fake_worker(calls))
    assert result["status"]=="optimal" and result["completed_algorithm_execution_count"]==12
    assert len(calls)==12
    assert [(c["budget_index"],c["algorithm"],c["repetition"]) for c in calls]==[
        *[(0,"cold",r) for r in (1,2,3)],*[(0,"warm",r) for r in (1,2,3)],
        *[(1,"warm",r) for r in (1,2,3)],*[(1,"cold",r) for r in (1,2,3)],
    ]
    assert all(calls[6+i]["previous_state"] is not None for i in range(3))


def test_solver_timeout_is_immutable_and_stops_sequence(tmp_path) -> None:
    calls=[]; context=_context(tmp_path); case=FormalCase("case",2026091101,"C0")
    with pytest.raises(RuntimeError):
        _run_formal_sequence(root=ROOT,context=context,case=case,run_id="timeout_case",execution_root=tmp_path,worker_executor=_fake_worker(calls,fail_at=2))
    assert len(calls)==2
    status=json.loads((tmp_path/"runs/timeout_case/status_summary.json").read_text())
    assert status["status"]=="timeout"


def test_projection_closes_only_exact_20_40_240(monkeypatch,tmp_path) -> None:
    context=_context(tmp_path); context["cases"]=tuple(FormalCase(f"case{i}",2026091101+i//2,("C0","T03")[i%2]) for i in range(20))
    execution=tmp_path/"formal"; (execution/"runs").mkdir(parents=True)
    rows=[]
    for case in context["cases"]:
        components={"latent_draw_sha256":"1"*64,"demand_sha256":"2"*64,"fulfillment_sha256":("3" if case.profile_id=="C0" else "4")*64,"emergency_price_sha256":"5"*64,"emergency_supply_sha256":"6"*64,"scenario_order_sha256":"7"*64}
        result={"status":"optimal","run_id":case.case_id,"case_id":case.case_id,"seed":case.seed,"profile_id":case.profile_id,"execution_mode":"formal","fingerprints":context["fingerprints"],"execution_identity":context["synchronized_main"],"comparisons":[{"methods":{"cold":[{"component_set_sha256":components}]}},{"methods":{"cold":[{"component_set_sha256":components}]}}]}
        directory=execution/"runs"/case.case_id; directory.mkdir(); (directory/"result.json").write_text(json.dumps(result))
        digest=hashlib.sha256((directory/"result.json").read_bytes()).hexdigest(); (directory/"manifest.json").write_text(json.dumps({"result_sha256":digest}))
        rows.append({"run_id":case.case_id,"case_id":case.case_id,"parent_run_id":None,"status":"optimal"})
    (execution/"run_registry.json").write_text(json.dumps({"runs":rows}))
    monkeypatch.setattr("src.phase6_m2_algorithm_performance_formal._validate_result",lambda *args:{"execution_count":12,"budget_pair_count":2,"timing":[]})
    projection=update_projection(execution,context)
    assert projection["formal_algorithm_performance_gate_passed"] is True
    assert projection["completed_algorithm_execution_count"]==240
    rows[0]["status"]="timeout"; (execution/"run_registry.json").write_text(json.dumps({"runs":rows}))
    assert update_projection(execution,context)["formal_algorithm_performance_gate_passed"] is False


def test_bounded_status_reader(tmp_path) -> None:
    path=tmp_path/"status.json"; assert read_status(path)["status"]=="not_started"
    path.write_text(json.dumps({"status":"running"})); assert read_status(path)["status"]=="running"
    path.write_text("x"*17000)
    with pytest.raises(ValueError): read_status(path)
