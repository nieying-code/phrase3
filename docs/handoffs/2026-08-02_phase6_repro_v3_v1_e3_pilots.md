# Phase 6 Reproducibility v3 V1 E3 Pilot Handoff

## 任务目标

在PR #22合并后的全新复现基线上，重新建立V1 E3 pilot门槛。仅运行三个批准的pilot种子，不运行family、V2、P1、P2或任何正式种子。

## 分支和提交

- Branch: `agent/phase6-v1-repro-baseline`
- Base: merged PR #22, `92f92b8fa8f85436797a7f9f4b20295ab09a3b35`
- Execution tree: `384b6ddd523d45c468068f466c41c0c6eec31d1e`
- Result commit: `645bbc1bb4a1166cbbb1bc8a4e7cd6fb4f4043a5`
- Draft PR: https://github.com/nieying-code/phrase3/pull/23

## 执行范围

- Tier: V1（1种物资、6期、50个训练场景）
- Seeds: `2026072001`, `2026072002`, `2026072003`
- Budgets: `0.90`, `1.10`, `1.30 × B_ref`
- Algorithms: standard C&CG cold start and SPW-C&CG warm start
- Repetitions: 1 per algorithm, seed and budget
- Total: 3 runs, 9 budget pairs, 18 algorithm executions

## 干净基线与环境

三个manifest均记录：tracked工作树干净、未跟踪执行输入为0。受控输出位于全新的`outputs/phase6_v21_repro_v3/`，旧registry和projection未复制进入该目录。

- Scientific config: `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3`
- E3 component: `fd0dc3ea77f850615502005e2caf9f3b7c0259d7c11a9efc7e2a30025c404083`
- Family component: `92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e`
- Environment: `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`
- Python: CPython 3.12.10
- Gurobi/gurobipy: 13.0.2
- Pyomo interface: `gurobi_direct`
- Threads: 1

## 数值结果

- Primary runs: 3/3 optimal
- Budget pairs: 9/9 optimal
- Algorithm executions: 18/18 optimal
- Maximum cold/warm objective difference: 0.0
- Infeasible recourse: 0
- Solver failures: 0
- Duplicate primary runs: 0
- Parent/diagnostic runs: 0
- Total C&CG iterations: 20
- Total algorithm wall time: 28.029809 seconds
- Maximum peak memory: 75.386719 MB
- `early_disposal`, `expired_waste`, `total_disposal`: present in every exact scenario evaluation inspected

## 投影状态

当前新基线E3覆盖为`3/12`，family run为0。`compute_gate_passed=false`且`formal_execution_authorized=false`是预期结果，不得启动正式实验。

## 审计材料

- Compact audit: `docs/handoffs/2026-08-02_phase6_repro_v3_v1_e3_pilots_audit.json`
- Audit test: `tests/test_phase6_repro_v3_v1_pilot_audit.py`
- 原始result、checkpoint、场景和日志保留在D盘ignored输出根目录，不提交GitHub。

## 验证结果

- Audit test: `1 passed in 0.06s`
- Full regression: `154 passed in 35.86s`
- `git diff --check`: passed
- GitHub Actions: pending

## 下一步与停止边界

本PR通过ChatGPT复审并由用户手动合并后，才可使用同一新输出根目录按每个种子`E1 → E2 → E4 → E5`顺序重建family pilot。当前不得运行family或任何更大档位。

## ChatGPT审查清单

1. 三个run是否来自PR #22合并后的相同干净Git tree；
2. 三类运行指纹和环境指纹是否一致；
3. 3/9/18计数及冷热目标一致性是否正确；
4. 是否存在补救不可行、求解失败、重复或诊断重试；
5. 三个库存处置字段是否完整；
6. 投影是否严格停留在3/12且未授权正式实验；
7. 是否没有运行family、V2、P1、P2或正式种子。
