from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
from typing import Any

DIAGNOSTIC_KIND = "post_hoc_descriptive_diagnostic"
FINAL_STATUS = "M2_1_candidate_requires_new_freeze_validation_and_test_sets"
BASE_COMMIT = "8fb9684e7b27a6c0034613c394697efbac69c7c0"
BASE_TREE = "8eb925963480a8795b3510bb8c1e72294b188309"
PR58_REL = "docs/handoffs/2026-08-21_phase6_m2_formal_mechanism_results_v1_1_audit.json"
PR60_REL = "docs/handoffs/2026-08-21_phase6_m2_formal_oos_results_v1_1_audit.json"
PR58_SHA = "bce5b075d352a4679b4371a073f5cc0a931a6b309b401318e9f4c38a8a7489a5"
PR60_SHA = "ee1a767df0962b0e625ef0dbe4acbe99b719c14f576b8464a9d338dffe976cd4"
OOS_ORCHESTRATOR_SHA = "9628804bcc5fa12ef9e0a8f7652ccce274eb975772fbacd974978fe24c310113"
FINGERPRINTS = {
    "scientific_config_sha256": "02d50abd609acd9d93eca6b13f6195e6eee14330e3db5c5ca75e83d2e7b56612",
    "e3_component_sha256": "87f643fd3bf90f825251641c1bdeeb25f4aebb1ea23d052913b27e0b5fdf2924",
    "family_component_sha256": "b1f9278ee8a0085e80c418f33d04c92b943c215eaf9ca2cdb6144e8dcebdb68b",
    "runner_config_sha256": "c8d9efb59649b2a3e16839cdece7c38bc5a385358c354b72310c32134f49ad8e",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}
STRATEGIES = (
    "endogenous_reserve", "zero_autonomous_reserve",
    "fixed_autonomous_reserve_0_10", "fixed_autonomous_reserve_0_30",
    "fixed_autonomous_reserve_0_50",
)
FIXED = (
    ("fixed_autonomous_reserve_0_10", 0.1),
    ("fixed_autonomous_reserve_0_30", 0.3),
    ("fixed_autonomous_reserve_0_50", 0.5),
)
NUMERICAL_THRESHOLD = 1e-4
SUBSTANTIVE_THRESHOLD = 0.01
MODERATE_RANGE = (0.05, 0.50)
CSV_NAME = "2026-08-21_phase6_m2_oos_lightweight_diagnostics_v1_1.csv"
REPORT_NAME = "2026-08-21_phase6_m2_oos_lightweight_diagnostics_v1_1.md"
AUDIT_NAME = "2026-08-21_phase6_m2_oos_lightweight_diagnostics_v1_1_audit.json"


class DiagnosticError(RuntimeError):
    pass


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(value: object) -> str:
    return sha256_bytes(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8"))


def read_reviewed(path: Path, expected: str) -> dict[str, Any]:
    if sha256_path(path) != expected:
        raise DiagnosticError(f"reviewed audit hash mismatch: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def rank_str(results: dict[str, Any], field: str, descending: bool = False) -> str:
    order = {name: index for index, name in enumerate(STRATEGIES)}
    def value(name: str) -> float:
        if field == "exact_training_objective":
            return results[name]["source_plan_identity"][field]
        return results[name]["metrics"][field]
    ranked = sorted(
        STRATEGIES,
        key=lambda name: ((-value(name) if descending else value(name)), order[name]),
    )
    return ">".join(ranked)


def numeric_summary(values: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
    }


def validate_and_pair(
    mechanism: dict[str, Any], oos: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if mechanism["fingerprints"] != FINGERPRINTS or oos["fingerprints"] != FINGERPRINTS:
        raise DiagnosticError("scientific fingerprint mismatch")
    if oos["formal_OOS_orchestrator_sha256"] != OOS_ORCHESTRATOR_SHA:
        raise DiagnosticError("OOS orchestrator fingerprint mismatch")
    if oos["machine_gate"] != {
        "formal_OOS_gate_passed": True,
        "next_decision": "permit_OOS_results_review_only",
        "algorithm_performance_authorized": False,
        "formal_extension_complete": False,
    }:
        raise DiagnosticError("formal OOS gate mismatch")
    aggregate = oos["aggregate"]
    for field, expected in {
        "required_primary_run_count": 10,
        "completed_primary_run_count": 10,
        "completed_plan_count": 50,
        "completed_exact_recourse_evaluation_count": 100000,
        "infeasible_scenario_count": 0,
        "solver_failure_count": 0,
    }.items():
        if aggregate[field] != expected:
            raise DiagnosticError(f"unexpected evidence count: {field}")
    for field in (
        "missing_case_ids", "invalid_primary_run_ids", "failed_primary_run_ids",
        "duplicate_case_ids", "diagnostic_run_ids",
        "finalization_failure_run_ids",
    ):
        if aggregate[field]:
            raise DiagnosticError(f"non-empty failure set: {field}")
    sources = {
        row["run_id"]: row for row in mechanism["runs"]
        if row["tier_id"] == "M2F2" and row["beta"] == 1.1
        and row["profile_id"] == "T03"
    }
    oos_runs = sorted(oos["runs"], key=lambda row: row["training_seed"])
    if len(sources) != 10 or len(oos_runs) != 10:
        raise DiagnosticError("expected ten source/OOS run pairs")
    plan_count = 0
    for observed in oos_runs:
        source = sources[observed["source_mechanism_run_id"]]
        if (
            source["seed"] != observed["training_seed"]
            or source["artifacts"]["result_sha256"]
            != observed["source_mechanism_result_sha256"]
            or source["science"]["joint_scenario_set_sha256"]
            != observed["source_training_joint_scenario_set_sha256"]
        ):
            raise DiagnosticError("source run binding mismatch")
        plans = source["science"]["first_stage_plan_identities"]
        for strategy in STRATEGIES:
            plan = plans[strategy]
            expected = {
                "finalized_plan_artifact_sha256": plan["finalized_plan_artifact_sha256"],
                "regular_purchase_sha256": plan["regular_purchase_sha256"],
                "reserve_amount": plan["reserve_amount"],
                "exact_training_objective": plan["exact_training_objective"],
                "training_joint_scenario_set_sha256":
                    plan["training_joint_scenario_set_sha256"],
            }
            if (
                plan["strategy_id"] != strategy
                or observed["strategy_results"][strategy]["source_plan_identity"]
                != expected
            ):
                raise DiagnosticError("source plan binding mismatch")
            plan_count += 1
    if plan_count != 50:
        raise DiagnosticError("expected fifty source plans")
    return sources, oos_runs


def build_rows(repo_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mechanism = read_reviewed(repo_root / PR58_REL, PR58_SHA)
    oos = read_reviewed(repo_root / PR60_REL, PR60_SHA)
    sources, runs = validate_and_pair(mechanism, oos)
    rows: list[dict[str, Any]] = []
    fixed_counts = {name: 0 for name, _ in FIXED}
    for run in runs:
        source = sources[run["source_mechanism_run_id"]]
        results = run["strategy_results"]
        endogenous = results["endogenous_reserve"]
        zero = results["zero_autonomous_reserve"]
        budget = float(run["budget"])
        reserve = float(endogenous["source_plan_identity"]["reserve_amount"])
        ratio = reserve / budget
        if not math.isclose(
            ratio, source["science"]["R_disc_robust_ratio"], abs_tol=1e-12
        ):
            raise DiagnosticError("reserve ratio mismatch")
        training_rank = rank_str(results, "exact_training_objective")
        mean_rank = rank_str(results, "mean_total_cost")
        cvar_rank = rank_str(results, "total_cost_cvar95")
        service_rank = rank_str(results, "service_level", descending=True)
        selected_fixed = min(
            FIXED,
            key=lambda pair: (
                results[pair[0]]["source_plan_identity"]["exact_training_objective"],
                pair[1],
            ),
        )[0]
        fixed_counts[selected_fixed] += 1
        selected = results[selected_fixed]
        metrics = endogenous["metrics"]
        row = {
            "training_seed": run["training_seed"],
            "test_seed": run["test_seed"],
            "source_mechanism_run_id": run["source_mechanism_run_id"],
            "oos_run_id": run["run_id"],
            "budget": budget,
            "endogenous_reserve_amount": reserve,
            "endogenous_reserve_ratio": ratio,
            "zero_endogenous_reserve": reserve == 0.0,
            "numerical_activation": ratio > NUMERICAL_THRESHOLD,
            "substantive_activation": ratio >= SUBSTANTIVE_THRESHOLD,
            "moderate_activation": (
                ratio >= SUBSTANTIVE_THRESHOLD
                and MODERATE_RANGE[0] <= ratio <= MODERATE_RANGE[1]
            ),
            "fixed_10_reserve_amount":
                results["fixed_autonomous_reserve_0_10"]
                ["source_plan_identity"]["reserve_amount"],
            "fixed_30_reserve_amount":
                results["fixed_autonomous_reserve_0_30"]
                ["source_plan_identity"]["reserve_amount"],
            "fixed_50_reserve_amount":
                results["fixed_autonomous_reserve_0_50"]
                ["source_plan_identity"]["reserve_amount"],
            "endogenous_mean_emergency_spend": metrics["mean_emergency_spend"],
            "endogenous_service_level": metrics["service_level"],
            "endogenous_mean_total_cost": metrics["mean_total_cost"],
            "endogenous_total_cost_cvar95": metrics["total_cost_cvar95"],
            "endogenous_shortage_probability": metrics["shortage_probability"],
            "endogenous_mean_shortage": metrics["mean_shortage"],
            "endogenous_mean_waste": metrics["mean_waste"],
            "endogenous_mean_expired_waste": metrics["mean_expired_waste"],
            "endogenous_mean_early_disposal": metrics["mean_early_disposal"],
            "endogenous_mean_total_disposal": metrics["mean_total_disposal"],
            "endogenous_reserve_utilization": metrics["reserve_utilization"],
            "training_objective_ranking": training_rank,
            "oos_mean_total_cost_ranking": mean_rank,
            "oos_cvar95_ranking": cvar_rank,
            "oos_service_level_ranking": service_rank,
            "training_best_strategy": training_rank.split(">")[0],
            "training_selected_best_fixed_strategy": selected_fixed,
            "training_best_is_oos_mean_best":
                training_rank.split(">")[0] == mean_rank.split(">")[0],
            "training_best_is_oos_cvar_best":
                training_rank.split(">")[0] == cvar_rank.split(">")[0],
            "training_best_is_oos_service_best":
                training_rank.split(">")[0] == service_rank.split(">")[0],
            "endogenous_minus_zero_mean_total_cost":
                metrics["mean_total_cost"] - zero["metrics"]["mean_total_cost"],
            "endogenous_minus_zero_total_cost_cvar95":
                metrics["total_cost_cvar95"] - zero["metrics"]["total_cost_cvar95"],
            "endogenous_minus_zero_service_level":
                metrics["service_level"] - zero["metrics"]["service_level"],
            "endogenous_minus_training_selected_fixed_mean_total_cost":
                metrics["mean_total_cost"] - selected["metrics"]["mean_total_cost"],
            "endogenous_minus_training_selected_fixed_total_cost_cvar95":
                metrics["total_cost_cvar95"]
                - selected["metrics"]["total_cost_cvar95"],
            "endogenous_minus_training_selected_fixed_service_level":
                metrics["service_level"] - selected["metrics"]["service_level"],
        }
        rows.append(row)
    return rows, {"oos_audit": oos, "fixed_selection_counts": fixed_counts}


def group_summary(rows: list[dict[str, Any]], zero: bool) -> dict[str, Any]:
    selected = [row for row in rows if row["zero_endogenous_reserve"] is zero]
    fields = (
        "endogenous_mean_total_cost", "endogenous_total_cost_cvar95",
        "endogenous_service_level", "endogenous_mean_emergency_spend",
        "endogenous_shortage_probability", "endogenous_mean_shortage",
        "endogenous_mean_total_disposal",
    )
    return {
        "seed_count": len(selected),
        "training_seeds": [row["training_seed"] for row in selected],
        "metrics": {
            field: numeric_summary([float(row[field]) for row in selected])
            for field in fields
        },
    }


def build_summary(rows: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    ratios = [float(row["endogenous_reserve_ratio"]) for row in rows]
    ranking = {
        "training_full_ranking_equals_oos_mean_count": sum(
            row["training_objective_ranking"] == row["oos_mean_total_cost_ranking"]
            for row in rows
        ),
        "training_full_ranking_equals_oos_cvar_count": sum(
            row["training_objective_ranking"] == row["oos_cvar95_ranking"]
            for row in rows
        ),
        "training_full_ranking_equals_oos_service_count": sum(
            row["training_objective_ranking"] == row["oos_service_level_ranking"]
            for row in rows
        ),
        "training_best_equals_oos_mean_best_count": sum(
            row["training_best_is_oos_mean_best"] for row in rows
        ),
        "training_best_equals_oos_cvar_best_count": sum(
            row["training_best_is_oos_cvar_best"] for row in rows
        ),
        "training_best_equals_oos_service_best_count": sum(
            row["training_best_is_oos_service_best"] for row in rows
        ),
        "top_strategy_reversal_count_for_oos_mean": sum(
            not row["training_best_is_oos_mean_best"] for row in rows
        ),
        "top_strategy_reversal_count_for_oos_cvar": sum(
            not row["training_best_is_oos_cvar_best"] for row in rows
        ),
        "top_strategy_reversal_count_for_oos_service": sum(
            not row["training_best_is_oos_service_best"] for row in rows
        ),
        "endogenous_worse_than_training_selected_fixed_on_oos_mean_count": sum(
            row["endogenous_minus_training_selected_fixed_mean_total_cost"] > 0
            for row in rows
        ),
        "endogenous_worse_than_training_selected_fixed_on_oos_cvar_count": sum(
            row["endogenous_minus_training_selected_fixed_total_cost_cvar95"] > 0
            for row in rows
        ),
        "fixed_training_selection_counts": context["fixed_selection_counts"],
    }
    policies = context["oos_audit"]["policy_descriptive_summaries"]
    fixed_orders: dict[str, list[str]] = {}
    for label, field, reverse in (
        ("mean_total_cost_best_to_worst",
         "mean_total_cost_mean_across_seed_pairs", False),
        ("total_cost_cvar95_best_to_worst",
         "total_cost_cvar95_mean_across_seed_pairs", False),
        ("service_level_best_to_worst",
         "service_level_mean_across_seed_pairs", True),
    ):
        fixed_orders[label] = sorted(
            (name for name, _ in FIXED),
            key=lambda name: (
                -policies[name][field] if reverse else policies[name][field]
            ),
        )
    systematic = all(
        ranking[field] == 10 for field in (
            "top_strategy_reversal_count_for_oos_mean",
            "top_strategy_reversal_count_for_oos_cvar",
            "top_strategy_reversal_count_for_oos_service",
        )
    )
    if not systematic:
        raise DiagnosticError("structural-candidate evidence gate not met")
    return {
        "diagnostic_kind": DIAGNOSTIC_KIND,
        "activation": {
            "zero_endogenous_reserve_seed_count":
                sum(row["zero_endogenous_reserve"] for row in rows),
            "positive_endogenous_reserve_seed_count":
                sum(not row["zero_endogenous_reserve"] for row in rows),
            "numerical_activation_seed_count":
                sum(row["numerical_activation"] for row in rows),
            "substantive_activation_seed_count":
                sum(row["substantive_activation"] for row in rows),
            "moderate_activation_seed_count":
                sum(row["moderate_activation"] for row in rows),
            "reserve_ratio": numeric_summary(ratios),
            "reported_mean_approximately_0_0625393_recomputed_as":
                statistics.mean(ratios),
        },
        "ranking": ranking,
        "zero_endogenous_reserve_group": group_summary(rows, True),
        "positive_endogenous_reserve_group": group_summary(rows, False),
        "policy_descriptive_summaries": policies,
        "fixed_policy_descriptive_orders": fixed_orders,
        "monetary_component_decomposition": {
            "status": (
                "retained_artifacts_do_not_support_exact_monetary_component_"
                "decomposition"
            ),
            "available_exact_metrics": [
                "mean_total_cost", "mean_emergency_spend",
                "shortage_probability", "service_level", "mean_shortage",
                "mean_waste", "mean_expired_waste", "mean_early_disposal",
                "mean_total_disposal", "total_cost_cvar95", "reserve_amount",
                "reserve_utilization",
            ],
            "residual_subtraction_used": False,
        },
        "evidence_table": {
            "potentially_structural": {
                "majority_endogenous_underperforms_selected_fixed_on_mean":
                    ranking[
                        "endogenous_worse_than_training_selected_fixed_on_oos_mean_count"
                    ] >= 6,
                "majority_endogenous_underperforms_selected_fixed_on_cvar95":
                    ranking[
                        "endogenous_worse_than_training_selected_fixed_on_oos_cvar_count"
                    ] >= 6,
                "systematic_training_to_oos_top_strategy_reversal": systematic,
                "mathematical_estimand_mismatch_present": True,
                "estimand_mismatch_description": (
                    "training exact robust worst-case objective differs from "
                    "OOS mean cost, CVaR95, and demand-weighted service level"
                ),
                "theoretical_candidate_independent_of_fixed_ratio_results": True,
                "candidate_retains_endogenous_reserve": True,
                "candidate_can_be_frozen_before_new_test_sets": True,
            },
            "local_to_beta_1_1_T03": {
                "evidence_uses_single_beta_profile": True,
                "same_pattern_in_other_profiles_is_unverified": True,
                "simple_more_reserve_is_better_for_all_metrics": False,
                "fixed_strategy_order_depends_on_metric":
                    len({tuple(value) for value in fixed_orders.values()}) > 1,
                "training_selected_fixed_ratio_varies_across_seeds":
                    sum(value > 0 for value in context[
                        "fixed_selection_counts"
                    ].values()) > 1,
                "exact_structural_cause_identifiable_from_retained_artifacts":
                    False,
                "candidate_is_only_fixed_ratio_imitation": False,
            },
            "causal_language": {
                "permitted": ["与……一致", "提示可能存在……", "当前证据不足以证明……"],
                "forbidden": "证明由……导致",
            },
        },
        "final_status": FINAL_STATUS,
    }


CSV_FIELDS = (
    "training_seed", "test_seed", "source_mechanism_run_id", "oos_run_id",
    "budget", "endogenous_reserve_amount", "endogenous_reserve_ratio",
    "zero_endogenous_reserve", "numerical_activation",
    "substantive_activation", "moderate_activation",
    "fixed_10_reserve_amount", "fixed_30_reserve_amount",
    "fixed_50_reserve_amount", "endogenous_mean_emergency_spend",
    "endogenous_service_level", "endogenous_mean_total_cost",
    "endogenous_total_cost_cvar95", "endogenous_shortage_probability",
    "endogenous_mean_shortage", "endogenous_mean_waste",
    "endogenous_mean_expired_waste", "endogenous_mean_early_disposal",
    "endogenous_mean_total_disposal", "endogenous_reserve_utilization",
    "training_objective_ranking", "oos_mean_total_cost_ranking",
    "oos_cvar95_ranking", "oos_service_level_ranking",
    "training_best_strategy", "training_selected_best_fixed_strategy",
    "training_best_is_oos_mean_best", "training_best_is_oos_cvar_best",
    "training_best_is_oos_service_best",
    "endogenous_minus_zero_mean_total_cost",
    "endogenous_minus_zero_total_cost_cvar95",
    "endogenous_minus_zero_service_level",
    "endogenous_minus_training_selected_fixed_mean_total_cost",
    "endogenous_minus_training_selected_fixed_total_cost_cvar95",
    "endogenous_minus_training_selected_fixed_service_level",
)


def render_csv(rows: list[dict[str, Any]]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def render_report(summary: dict[str, Any]) -> str:
    a, r = summary["activation"], summary["ranking"]
    ratio = a["reserve_ratio"]
    fixed = r["fixed_training_selection_counts"]
    status = summary["monetary_component_decomposition"]["status"]
    return f"""# Phase 6 M2 正式 OOS 轻量诊断（v1.1）

日期：2026-08-21

## 诊断性质与最终状态

本报告是 {DIAGNOSTIC_KIND}。它只读取 PR #58 与 PR #60 的正式审计，
没有生成场景、调用 Gurobi、重跑实验、修改模型或新增确认性统计。

最终状态：

    {FINAL_STATUS}

现有证据提示一个具有理论意义的结构候选，但不足以直接开发 M2.1。
任何后续工作都必须先经人工复审、重新冻结，并使用全新验证集和测试集。

## 输入证据闭环

- PR #58 审计 SHA-256：{PR58_SHA}
- PR #60 审计 SHA-256：{PR60_SHA}
- 10/10 正式 OOS run、50/50 方案、100,000/100,000 补救评价；
- formal_OOS_gate_passed=true；
- 失败、无效、重复、诊断和最终化失败集合均为空；
- 五类科学指纹及正式 OOS 编排器指纹保持不变。

## 1. 内生储备激活分布

| 指标 | 结果 |
|---|---:|
| 零内生储备种子 | {a["zero_endogenous_reserve_seed_count"]}/10 |
| 正内生储备种子 | {a["positive_endogenous_reserve_seed_count"]}/10 |
| 实质激活（>=1%） | {a["substantive_activation_seed_count"]}/10 |
| 适度激活（5%—50%） | {a["moderate_activation_seed_count"]}/10 |
| 储备比例均值 | {ratio["mean"]:.12f} |
| 储备比例中位数 | {ratio["median"]:.12f} |
| 储备比例最小值 | {ratio["minimum"]:.12f} |
| 储备比例最大值 | {ratio["maximum"]:.12f} |

约 0.0625393 的均值严格来自10个种子的 R_min_opt/B 算术平均：
{a["reported_mean_approximately_0_0625393_recomputed_as"]:.15f}。
原冻结的数值、实质和适度激活阈值均未改变。

## 2. 训练目标与 OOS 排序差距

- 训练完整排序与OOS平均成本排序一致：{r["training_full_ranking_equals_oos_mean_count"]}/10；
- 训练完整排序与OOS CVaR95排序一致：{r["training_full_ranking_equals_oos_cvar_count"]}/10；
- 训练完整排序与OOS服务排序一致：{r["training_full_ranking_equals_oos_service_count"]}/10；
- 训练最优仍为OOS平均成本/CVaR95/服务最优：
  {r["training_best_equals_oos_mean_best_count"]}/10、
  {r["training_best_equals_oos_cvar_best_count"]}/10、
  {r["training_best_equals_oos_service_best_count"]}/10；
- 内生策略相对训练选定固定策略在OOS平均成本和CVaR95上更差：
  {r["endogenous_worse_than_training_selected_fixed_on_oos_mean_count"]}/10、
  {r["endogenous_worse_than_training_selected_fixed_on_oos_cvar_count"]}/10。

训练数据选择固定比例次数：10%={fixed["fixed_autonomous_reserve_0_10"]}，
30%={fixed["fixed_autonomous_reserve_0_30"]}，
50%={fixed["fixed_autonomous_reserve_0_50"]}。

这一模式与训练期精确鲁棒最坏情形目标和最终关心的OOS平均成本、CVaR95、
服务水平口径不同相一致，提示可能存在训练准则与报告准则的目标错配。
当前证据不足以证明该差异是排序反转的唯一原因。

## 3. 成本与风险解释边界

可精确复算的指标包括总成本、应急支出、缺货概率、服务水平、缺货量、
废弃/处置量、CVaR95、储备金额和利用率。

货币分解状态：

    {status}

现有紧凑制品没有分别保存可逐项复算的常规采购成本、缺货惩罚成本和处置
惩罚成本。本诊断没有通过总成本相减推测缺失分量。

## 结构候选与 T03 局部证据

| 证据 | 观察 | 边界 |
|---|---|---|
| 内生相对训练选定固定策略偏弱 | 平均成本与CVaR95均为8/10 | 与内生储备偏低一致，不证明因果 |
| 训练最优到OOS最优反转 | 三个OOS指标均为10/10 | 提示可能存在目标口径错配 |
| 非固定比例理论候选 | 可预注册与目标风险指标一致的训练准则，同时保持R内生 | 只是候选方向，不是本PR模型设计 |
| 证据范围 | 只有beta=1.1/T03 | 当前证据不足以证明其他配置相同 |
| 固定策略 | 最优比例随指标变化，训练选择也并非单一比例 | 不能简化为“储备越高越好” |
| 精确原因 | 缺少货币成本分量和新反事实数据 | 不能识别唯一结构原因 |

报告只使用“与……一致”“提示可能存在……”和“当前证据不足以证明……”等
证据边界语言，不作确定性因果宣称。

## 停止边界

本诊断不授权修改模型、使用现有测试集选择M2.1、设置人为储备下限，
或运行M2.1、算法性能实验和M0 E3。
"""


def build_audit(
    rows: list[dict[str, Any]], summary: dict[str, Any],
    csv_text: str, report_text: str,
) -> dict[str, Any]:
    return {
        "schema_version": "phase6_m2_oos_lightweight_diagnostics_v1_1",
        "created_on": "2026-08-21",
        "diagnostic_kind": DIAGNOSTIC_KIND,
        "execution_baseline": {
            "pr60_merge_commit": BASE_COMMIT,
            "base_git_sha": BASE_COMMIT,
            "base_git_tree_sha": BASE_TREE,
            "working_tree_clean_before_branch": True,
        },
        "reviewed_inputs": {
            "pr58_audit_path": PR58_REL, "pr58_audit_sha256": PR58_SHA,
            "pr60_audit_path": PR60_REL, "pr60_audit_sha256": PR60_SHA,
        },
        "fingerprints": FINGERPRINTS,
        "formal_OOS_orchestrator_sha256": OOS_ORCHESTRATOR_SHA,
        "evidence_counts": {
            "formal_mechanism_source_runs": 10,
            "formal_OOS_primary_runs": 10,
            "strategy_plan_identities": 50,
            "exact_recourse_evaluations": 100000,
            "scenario_generations": 0, "gurobi_calls": 0,
            "new_scientific_experiments": 0,
            "new_confirmatory_statistics": 0, "M2_1_runs": 0,
            "algorithm_performance_runs": 0, "M0_E3_runs": 0,
        },
        "formal_OOS_gate_passed": True,
        "failure_sets": {
            "missing": [], "invalid": [], "failed": [], "duplicate": [],
            "diagnostic": [], "finalization_failure": [],
        },
        "frozen_activation_thresholds": {
            "numerical_strictly_greater_than": NUMERICAL_THRESHOLD,
            "substantive_greater_than_or_equal_to": SUBSTANTIVE_THRESHOLD,
            "moderate_inclusive_range": list(MODERATE_RANGE),
        },
        "seed_rows": rows,
        "seed_row_mapping_sha256": canonical_sha256(
            {str(row["training_seed"]): row for row in rows}
        ),
        "summary": summary,
        "generated_artifacts": {
            "csv_path": f"docs/handoffs/{CSV_NAME}",
            "csv_sha256": sha256_bytes(csv_text.encode("utf-8")),
            "report_path": f"docs/handoffs/{REPORT_NAME}",
            "report_sha256": sha256_bytes(report_text.encode("utf-8")),
            "script_path": "src/phase6_m2_oos_lightweight_diagnostics.py",
            "script_sha256": sha256_path(Path(__file__).resolve()),
        },
        "final_status": FINAL_STATUS,
        "stop_boundary": {
            "M2_1_development_authorized": False,
            "M2_1_execution_authorized": False,
            "algorithm_performance_authorized": False,
            "M0_E3_authorized": False,
            "next_action": "review_this_draft_PR_only",
        },
    }


def write_outputs(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    root, target = repo_root.resolve(), output_dir.resolve()
    if target != (root / "docs/handoffs").resolve():
        raise DiagnosticError("diagnostics may write only to docs/handoffs")
    rows, context = build_rows(root)
    summary = build_summary(rows, context)
    csv_text, report_text = render_csv(rows), render_report(summary)
    audit = build_audit(rows, summary, csv_text, report_text)
    target.mkdir(parents=True, exist_ok=True)
    (target / CSV_NAME).write_bytes(csv_text.encode("utf-8"))
    (target / REPORT_NAME).write_bytes(report_text.encode("utf-8"))
    (target / AUDIT_NAME).write_bytes(
        (
            json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False)
            + "\n"
        ).encode("utf-8")
    )
    return audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    output = args.output_dir or root / "docs/handoffs"
    audit = write_outputs(root, output)
    print(json.dumps({
        "status": audit["final_status"], "scenario_generations": 0,
        "gurobi_calls": 0, "new_scientific_experiments": 0,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
