from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.phase6_m2_algorithm_performance_formal import (
    GAP_NUMERICAL_PROTECTION, FormalCase, FormalEvidenceError, _method_metrics,
    _run_formal_sequence, _validate_result, build_formal_cases,
    compute_formal_statistics, read_status,
    run_formal_batch, update_projection, validate_preflight, validate_static_freeze,
)


ROOT=Path(__file__).resolve().parents[1]
RUNNER=ROOT/"configs/phase6_m2_algorithm_performance_formal_runner_v1_1.yaml"
APPROVAL=ROOT/"configs/phase6_m2_algorithm_performance_formal_approval_v1_1.yaml"


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
        return {"status":"optimal","solver_status":"optimal","algorithm":request["algorithm"],"repetition":request["repetition"],"seed":request["seed"],"profile_id":request["profile_id"],"beta":request["beta"],"budget":request["budget"],"objective":1000.0,"scenario_count":100,"joint_scenario_set_sha256":"a"*64,"component_set_sha256":components,"initial_scenarios":initial,"initial_scenario_pool_size":len(initial),"transfer_source_state_sha256":None if prior is None else _sha(prior),"transfer_source_budget":None if prior is None else prior["budget"],"transferred_exact_scenarios":transferred,"transferred_exact_scenario_count":len(transferred),"transferred_scenario_reuse_rate":0.0 if prior is None else len(transferred)/len(initial),"transferred_scenarios_becoming_active_or_worst":[n for n in transferred if n=="s0099"],"transferred_scenarios_becoming_active_or_worst_count":sum(n=="s0099" for n in transferred),"ccg_result":result,"scientific_result":result,"subprocess_wall_seconds":1.0,"sampled_peak_RSS_MiB":10.0,"failure":None}
    return execute


def _context(tmp_path):
    static=validate_static_freeze(ROOT,RUNNER,APPROVAL)
    static.update(fingerprints={"x":"y"},synchronized_main={"head":"1"*40},matrix={})
    return static


def _tampered_optimal_worker(calls, *, invalid_metric=False, invalid_transfer=False):
    execute = _fake_worker(calls)

    def tampered(request, timeout, directory):
        row = execute(request, timeout, directory)
        if invalid_metric and len(calls) == 1:
            row["ccg_result"]["gap"] = float("nan")
        if (
            invalid_transfer
            and request["budget_index"] == 1
            and request["algorithm"] == "warm"
            and request["repetition"] == 1
        ):
            row["transferred_exact_scenarios"] = []
            row["transferred_exact_scenario_count"] = 0
            row["transferred_scenario_reuse_rate"] = 0.0
        return row

    return tampered


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
    derived=_validate_result(result,case,context,expected_run_id="formal_case")
    assert derived["execution_count"]==12 and len(derived["timing"])==2


def test_formal_result_identity_and_false_transfer_tampering_are_rejected(tmp_path) -> None:
    context=_context(tmp_path); case=FormalCase("case",2026091101,"T03")
    result=_run_formal_sequence(root=ROOT,context=context,case=case,run_id="identity_case",execution_root=tmp_path,worker_executor=_fake_worker([]))
    mutations=[]
    for field,value in (("seed",0),("profile_id","C0"),("tier_id","V1"),("run_id","wrong")):
        def mutate(payload,field=field,value=value): payload[field]=value
        mutations.append(mutate)
    mutations.extend((
        lambda payload: payload["comparisons"][0].__setitem__("beta",9.9),
        lambda payload: payload["comparisons"][1].__setitem__("budget",1.0),
        lambda payload: payload["comparisons"][0]["methods"]["cold"][0].__setitem__("seed",0),
        lambda payload: payload["comparisons"][0]["methods"]["warm"][0].__setitem__("profile_id","C0"),
        lambda payload: payload["comparisons"][0]["methods"]["cold"][0].__setitem__("beta",9.9),
        lambda payload: payload["comparisons"][1]["methods"]["warm"][0].__setitem__("budget",1.0),
        lambda payload: payload["comparisons"][0]["methods"]["cold"][0].__setitem__("joint_scenario_set_sha256","f"*64),
        lambda payload: payload["comparisons"][0]["methods"]["cold"][0].__setitem__("transfer_source_state_sha256","f"*64),
    ))
    for mutate in mutations:
        tampered=deepcopy(result); mutate(tampered)
        with pytest.raises(ValueError):
            _validate_result(tampered,case,context,expected_run_id="identity_case")


def test_solver_timeout_is_immutable_and_stops_sequence(tmp_path) -> None:
    calls=[]; context=_context(tmp_path); case=FormalCase("case",2026091101,"C0")
    with pytest.raises(RuntimeError):
        _run_formal_sequence(root=ROOT,context=context,case=case,run_id="timeout_case",execution_root=tmp_path,worker_executor=_fake_worker(calls,fail_at=2))
    assert len(calls)==2
    status=json.loads((tmp_path/"runs/timeout_case/status_summary.json").read_text())
    assert status["status"]=="timeout"


@pytest.mark.parametrize("reported_gap", (-1.4551915228366852e-11, -1.0e-9))
def test_near_zero_negative_gap_is_preserved_and_normalized(reported_gap) -> None:
    request={"profile_id":"T03","algorithm":"cold","repetition":1,"seed":1,"beta":1.1,"budget":1.0}
    row=_fake_worker([])(request,1.0,ROOT)
    row["ccg_result"]["gap"]=reported_gap
    metrics=_method_metrics(row)
    assert metrics["reported_optimality_gap"]==reported_gap
    assert metrics["optimality_gap"]==0.0
    assert metrics["recomputed_upper_minus_lower"]==0.0


@pytest.mark.parametrize("reported_gap", (-1.0000001e-9,float("nan"),float("inf"),float("-inf")))
def test_materially_negative_or_nonfinite_gap_is_rejected(reported_gap) -> None:
    request={"profile_id":"T03","algorithm":"cold","repetition":1,"seed":1,"beta":1.1,"budget":1.0}
    row=_fake_worker([])(request,1.0,ROOT)
    row["ccg_result"]["gap"]=reported_gap
    with pytest.raises(ValueError):
        _method_metrics(row)


def test_reported_gap_must_match_upper_minus_lower_within_protection() -> None:
    request={"profile_id":"T03","algorithm":"cold","repetition":1,"seed":1,"beta":1.1,"budget":1.0}
    row=_fake_worker([])(request,1.0,ROOT)
    row["ccg_result"]["gap"]=GAP_NUMERICAL_PROTECTION+1.0e-12
    with pytest.raises(ValueError,match="upper minus lower"):
        _method_metrics(row)


def test_optimal_worker_with_invalid_metric_stops_before_next_solve(tmp_path) -> None:
    calls=[]; context=_context(tmp_path); case=FormalCase("case",2026091101,"C0")
    with pytest.raises(FormalEvidenceError):
        _run_formal_sequence(
            root=ROOT,context=context,case=case,run_id="invalid_metric_case",
            execution_root=tmp_path,
            worker_executor=_tampered_optimal_worker(calls,invalid_metric=True),
        )
    assert len(calls)==1
    run_dir=tmp_path/"runs/invalid_metric_case"
    status=json.loads((run_dir/"status_summary.json").read_text())
    result=json.loads((run_dir/"result.json").read_text())
    assert status["status"]=="evidence_invalid"
    assert result["status"]=="evidence_invalid"


def test_optimal_worker_with_invalid_transfer_stops_before_next_solve(tmp_path) -> None:
    calls=[]; context=_context(tmp_path); case=FormalCase("case",2026091101,"T03")
    with pytest.raises(FormalEvidenceError):
        _run_formal_sequence(
            root=ROOT,context=context,case=case,run_id="invalid_transfer_case",
            execution_root=tmp_path,
            worker_executor=_tampered_optimal_worker(calls,invalid_transfer=True),
        )
    assert len(calls)==7
    status=json.loads(
        (tmp_path/"runs/invalid_transfer_case/status_summary.json").read_text()
    )
    assert status["status"]=="evidence_invalid"


def test_invalid_optimal_worker_stops_batch_before_next_primary(monkeypatch,tmp_path) -> None:
    calls=[]; context=_context(tmp_path)
    context["runner"]=dict(context["runner"])
    context["runner"]["output_root"]="output"
    context["runner"]["formal_subdirectory"]="formal"
    context["cases"]=(
        FormalCase("case0",2026091101,"C0"),
        FormalCase("case1",2026091101,"T03"),
    )
    monkeypatch.setattr(
        "src.phase6_m2_algorithm_performance_formal.validate_preflight",
        lambda *args,**kwargs: context,
    )
    with pytest.raises(FormalEvidenceError):
        run_formal_batch(
            root=tmp_path,runner_path=RUNNER,approval_path=APPROVAL,
            authorize=True,run_id_prefix="invalid_batch",
            worker_executor=_tampered_optimal_worker(calls,invalid_metric=True),
        )
    assert len(calls)==1
    registry=json.loads(
        (tmp_path/"output/formal/run_registry.json").read_text()
    )["runs"]
    assert [row["case_id"] for row in registry]==["case0"]
    assert registry[0]["status"]=="evidence_invalid"
    assert not (tmp_path/"output/formal/runs/invalid_batch_case1").exists()


def test_projection_closes_only_exact_20_40_240(monkeypatch,tmp_path) -> None:
    context=_context(tmp_path); context["cases"]=tuple(FormalCase(f"case{i}",2026091101+i//2,("C0","T03")[i%2]) for i in range(20))
    execution=tmp_path/"formal"; (execution/"runs").mkdir(parents=True)
    rows=[]
    for case in context["cases"]:
        run_id=f"run_{case.case_id}"
        components={"latent_draw_sha256":"1"*64,"demand_sha256":"2"*64,"fulfillment_sha256":("3" if case.profile_id=="C0" else "4")*64,"emergency_price_sha256":"5"*64,"emergency_supply_sha256":"6"*64,"scenario_order_sha256":"7"*64}
        result={"status":"optimal","run_id":run_id,"case_id":case.case_id,"seed":case.seed,"profile_id":case.profile_id,"execution_mode":"formal","fingerprints":context["fingerprints"],"execution_identity":context["synchronized_main"],"comparisons":[{"methods":{"cold":[{"component_set_sha256":components}]}},{"methods":{"cold":[{"component_set_sha256":components}]}}]}
        directory=execution/"runs"/run_id; directory.mkdir(); (directory/"result.json").write_text(json.dumps(result))
        digest=hashlib.sha256((directory/"result.json").read_bytes()).hexdigest(); (directory/"manifest.json").write_text(json.dumps({"result_sha256":digest}))
        rows.append({"run_id":run_id,"case_id":case.case_id,"seed":case.seed,"profile_id":case.profile_id,"parent_run_id":None,"status":"optimal"})
    (execution/"run_registry.json").write_text(json.dumps({"runs":rows}))
    monkeypatch.setattr("src.phase6_m2_algorithm_performance_formal._validate_result",lambda *args,**kwargs:{"execution_count":12,"budget_pair_count":2,"timing":[]})
    monkeypatch.setattr("src.phase6_m2_algorithm_performance_formal.compute_formal_statistics",lambda *args,**kwargs:{"reliable_M2_T03_acceleration_gate_passed":False,"supply_disruption_enhances_warm_start_benefit_gate_passed":False})
    projection=update_projection(execution,context)
    assert projection["formal_algorithm_performance_gate_passed"] is True
    assert projection["completed_algorithm_execution_count"]==240
    rows[0]["status"]="timeout"; (execution/"run_registry.json").write_text(json.dumps({"runs":rows}))
    assert update_projection(execution,context)["formal_algorithm_performance_gate_passed"] is False
    rows[0]["status"]="optimal"; (execution/"run_registry.json").write_text(json.dumps({"runs":rows}))
    path=execution/"runs"/rows[0]["run_id"]/"result.json"
    payload=json.loads(path.read_text()); payload["seed"]=999; path.write_text(json.dumps(payload))
    (path.with_name("manifest.json")).write_text(json.dumps({"result_sha256":hashlib.sha256(path.read_bytes()).hexdigest()}))
    projection=update_projection(execution,context)
    assert projection["formal_algorithm_performance_gate_passed"] is False
    assert projection["common_random_number_mismatches"]


def test_preregistered_statistics_use_seed_medians_and_do_not_gate_completion() -> None:
    derived=[]
    for seed in range(2026091101,2026091111):
        for profile in ("C0","T03"):
            timing=[]
            for budget_index,beta in enumerate((1.1,1.3)):
                speedup=2.0 if profile=="T03" and budget_index==1 else 1.0
                timing.append({"seed":seed,"profile_id":profile,"budget_index":budget_index,"beta":beta,"budget":beta*100.0,"cold_median_seconds":20.0*speedup,"warm_median_seconds":20.0,"speedup_cold_over_warm":speedup})
            derived.append({"derived":{"timing":timing}})
    statistics=compute_formal_statistics(derived,correctness_gate_passed=True)
    assert statistics["primary_estimand"]["point_estimate"]==2.0
    assert statistics["primary_estimand"]["bootstrap_95_percentile_CI"]==[2.0,2.0]
    assert statistics["confirmatory_disruption_enhancement_estimand"]["point_estimate"]==2.0
    assert statistics["secondary_end_to_end_two_budget_speedup"]["T03"]==1.5
    assert statistics["reliable_M2_T03_acceleration_gate_passed"] is True
    assert statistics["supply_disruption_enhances_warm_start_benefit_gate_passed"] is True
    assert len(statistics["seed_level_values"])==10


def test_bounded_status_reader(tmp_path) -> None:
    path=tmp_path/"status.json"; assert read_status(path)["status"]=="not_started"
    path.write_text(json.dumps({"status":"running"})); assert read_status(path)["status"]=="running"
    path.write_text("x"*17000)
    with pytest.raises(ValueError): read_status(path)
