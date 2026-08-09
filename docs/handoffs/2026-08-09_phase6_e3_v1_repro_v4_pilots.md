# Phase 6 E3 V1 Repro-v4 Pilot Handoff

## 任务目标

在 PR #28 修复正式 E3 投影覆盖问题后，使用新 E3 指纹重新建立 V1 pilot 覆盖。本批次只运行 V1，不运行 V2、P1、P2 或正式种子。

## 执行基线

- Branch: `agent/phase6-e3-v1-repro-v4`
- PR #28 merged main: `1fa12bd9c3026ad202377d72fb79bfcd70c7c07e`
- Execution commit: `75ac9b852781e880c998dba0618a3f0b48195234`
- Execution tree: `e4f268fa170013f3d8bd52b3f71e5133c716571e`
- Merged main tree: `e4f268fa170013f3d8bd52b3f71e5133c716571e`
- Tree equivalence: exact
- Python: 3.12.10
- Gurobi/gurobipy: 13.0.2
- Pyomo interface: `gurobi_direct`
- Threads: 1
- Output root: `outputs/phase6_v21_repro_v3`

Git smart-HTTP 在运行前发生网络连接重置，无法把本地 `origin/main` 引用刷新到合并提交；GitHub API 已核验合并提交的 tree 与本地已合并 PR head 的 tree 完全相同。运行工作树 tracked 修改数为 0，执行内容与合并后 main 精确一致。

## 指纹

- Scientific config: `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3`
- E3 component: `20e1b80c1b117e8e801755d754f9005a8b386644c193dcb503396e4f3ec2cc5e`
- Family component: `92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e`
- E3 runner config: `3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd`
- Environment: `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`

## 预检结果

- 旧 E3 registry：12 条，均为旧指纹，不进入新门槛。
- 新 E3 registry：运行前 0 条。
- Family registry：12 条，全部重新验证 result/manifest 哈希通过。
- 计划 run ID 冲突：0。
- Python 进程：0。
- 残留锁：0。
- D 盘可用空间：约 455 GiB。
- 连续 formal 投影守卫专项测试：`11 passed in 6.23s`。

## 运行结果

运行顺序严格串行：

1. `pilot_e3_repro_v4_v1_2026072001`
2. `pilot_e3_repro_v4_v1_2026072002`
3. `pilot_e3_repro_v4_v1_2026072003`

汇总：

- Primary runs: 3/3 optimal
- Budget pairs: 9/9 optimal
- Algorithm executions: 18/18 optimal
- Maximum cold/warm objective difference: 0.0
- Failed/invalid/duplicate/diagnostic runs: 0
- `early_disposal` / `expired_waste` / `total_disposal`: 三条 run 均存在
- Solver: Gurobi 13.0.2, `gurobi_direct`, Threads=1

新投影状态：

```text
completed_run_count = 3
required_run_count = 12
status = insufficient_pilot_coverage
compute_gate_passed = false
formal_execution_authorized = false
```

该状态符合流程；缺少的 9 条为 V2、P1、P2 各三个种子。

## 制品与审计

- 原始结果保留在 D 盘受控输出根目录，未提交 GitHub。
- 紧凑机器审计：`docs/handoffs/2026-08-09_phase6_e3_v1_repro_v4_pilots_audit.json`
- 专项审计测试：`1 passed in 0.07s`
- 完整本地回归：`160 passed in 39.40s`
- `python -m compileall -q src tests`：通过
- `git diff --check`：通过
- Draft PR: pending
- Final result commit: pending
- CI: pending

## 停止边界

本批次完成后已停止。没有启动：

- V2 E3 pilot；
- P1/P2 E3 pilot；
- family pilot 重跑；
- family 最终投影重汇总；
- 任何正式实验。

## 下一步

本结果 PR 通过 ChatGPT 复审并由用户手动合并后，才可使用全新 run ID 严格串行运行 V2 E3 pilot。V2 完成后再次停止复审，不得自动进入 P1。
