# Phase 6 v2.1 V2 E3 Pilot Handoff

## 任务目标

在 V1 E3 pilot 与 family pilot 均复审通过并合并后，使用冻结矩阵和相对完全补救模型运行 V2 E3 pilot。每个冻结 pilot 种子包含三个预算、标准 C&CG 冷启动和 SPW-C&CG 热启动，并对每个算法执行三次技术计时重复。本批次完成后立即停止，不启动 P1、P2 或正式种子。

## 分支和提交

- Branch: `agent/phase6-v2-1-v2-e3-pilots`
- Remote main merge SHA: `3fc158b47c8e018577c6853a40fef6986a2f13a6`（PR #17 merge commit）
- Execution SHA: `5102724935888da1929337754d4b2a35366bced7`（PR #17 head）
- Execution/remote-main tree SHA: `db95c6f3f921da3757051a433748ebb9b82b54c1`
- Tree equality: confirmed
- Final validated V2 results head: `33a5267b8d1300246f7dad7d77f9c26ce9ef45e5`
- Draft PR: https://github.com/nieying-code/phrase3/pull/18
- Final validated V2 results CI: https://github.com/nieying-code/phrase3/actions/runs/30696021947 (`123 passed + 6 passed`)

`eb7a84a37549a015d69ea0281131edb0d9e2c0ba` 与 CI run `30695967027` 是 handoff 元数据最终化之前的中间状态，不作为最终验收状态。后续纯文档追溯提交不会改变实验结果、模型、矩阵或指纹；当前 PR head 及其 CI 以 GitHub PR checks 为准。

GitHub Git 数据端点在启动时短暂不可达，因此本地无法立即获取 merge commit 对象。GitHub API 独立确认 PR #17 已合并，且执行提交与远端最新 `main` 的 tree SHA 完全相同。换言之，运行使用的代码、配置、文档和依赖锁字节与最新 `main` 一致；该差异仅是 Git 合并提交对象，不是执行内容差异。

## 环境和基线

| 项目 | 值 |
|---|---|
| Matrix status | `frozen_for_formal_execution` |
| Scientific config SHA-256 | `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3` |
| E3 component SHA-256 | `7713671bab67eec8d99fdf776f1d645740d09d020ef31b55513ccc80595f951f` |
| Family component SHA-256 | `5803afd60d39a2e982d9b2c879453ef2d4e21755fcb46791810a1e1de8e5076f` |
| Environment SHA-256 | `0306c49cf953a79e3ade0fdf537e074dd17ddb942677333c62ef3f1bfb4782c2` |
| Python | `3.12.10` |
| Gurobi / gurobipy | `13.0.2 / 13.0.2` |
| Interface / threads | `gurobi_direct / 1` |
| HiGHS fallback | 禁止且未发生 |
| Initial E3 coverage | `3/12` |
| Family prerequisites | `12/12 runs, 30/30 work units, all optimal` |
| Initial formal authorization | `false` |

隔离输出根目录为 `outputs/phase6_v21_rr_clean`。执行前 `tracked_modified_count_at_start=0`，`working_tree_dirty=true` 来自以下未跟踪（untracked）输出目录，而不是已跟踪文件修改：

- `outputs/gurobi_validation/`
- `outputs/phase6_v21_rr_clean/`
- `outputs/relative_complete_recourse_validation/`
- `outputs/tmp/`

其中三个历史目录 `outputs/gurobi_validation/`、`outputs/relative_complete_recourse_validation/` 和 `outputs/tmp/` 没有作为本次 V2 运行输入。`outputs/phase6_v21_rr_clean/` 是本批次受控的当前读写根目录：runner 读取其中已经批准的 V1/family registry、projection 与前序制品，并向同一根目录写入 V2 结果。执行时不存在未提交的模型代码、科学配置、实验矩阵、runner 配置或依赖锁修改。

## 执行范围

严格串行运行三个全新 primary run：

- `pilot_rr_v21_e3_v2_primary_2026072001`
- `pilot_rr_v21_e3_v2_primary_2026072002`
- `pilot_rr_v21_e3_v2_primary_2026072003`

V2 参数：1 种物资、6 期、100 个训练场景、`0.90/1.10/1.30 × B_ref` 三档预算。每个种子、预算和算法执行三次技术重复，因此总计：

```text
3 seeds × 3 budgets × 2 algorithms × 3 repetitions = 54 executions
```

三次重复只用于技术计时中位数，不作为独立统计样本。

## 数值结果

| Seed | Budget factor | Cold objective | Warm objective | Difference | Cold/Warm median seconds |
|---:|---:|---:|---:|---:|---:|
| 2026072001 | 0.90 | 30620.790291 | 30620.790291 | 0.0 | 2.0997 / 2.0784 |
| 2026072001 | 1.10 | 25431.602136 | 25431.602136 | 0.0 | 2.0723 / 2.1023 |
| 2026072001 | 1.30 | 20301.417127 | 20301.417127 | 0.0 | 2.0936 / 2.0890 |
| 2026072002 | 0.90 | 17728.740006 | 17728.740006 | 0.0 | 2.0677 / 2.0852 |
| 2026072002 | 1.10 | 12593.369450 | 12593.369450 | 0.0 | 2.0654 / 2.0233 |
| 2026072002 | 1.30 | 7468.893507 | 7468.893507 | 0.0 | 2.0800 / 2.1163 |
| 2026072003 | 0.90 | 30866.353859 | 30866.353859 | 0.0 | 2.1053 / 2.0708 |
| 2026072003 | 1.10 | 25707.147715 | 25707.147715 | 0.0 | 2.1114 / 2.0997 |
| 2026072003 | 1.30 | 20577.903275 | 20577.903275 | 0.0 | 2.1072 / 2.0820 |

批次汇总：

- 3/3 primary runs optimal；
- 9/9 冷热预算配对 optimal；
- 54/54 算法执行 optimal（冷 27、热 27）；
- 18/18 技术重复组内目标完全一致；
- 最大组内目标差 `0.0`；
- 最大冷热目标差 `0.0`；
- 冷启动执行时间中位数 `2.093631 s`；
- 热启动执行时间中位数 `2.082210 s`；
- 峰值内存最大值 `76.097656 MB`；
- 无 solver failure、timeout、unexpected infeasible recourse、重复 primary、parent run 或 diagnostic retry；
- `early_disposal`、`expired_waste`、`total_disposal` 字段存在。

## 投影状态

- E3 coverage: `6/12`（V1 3条 + V2 3条）
- Failed primary: `0`
- Duplicate primary: `0`
- Diagnostic attempts: `0`
- Projection status: `insufficient_pilot_coverage`
- `compute_gate_passed=false`
- `formal_execution_authorized=false`
- Family prerequisites remain `12/12 runs, 30/30 work units, all optimal`

该状态符合冻结流程：P1 和 P2 尚未运行，正式实验仍未获授权。

## 机器审计

紧凑审计文件：`docs/handoffs/2026-08-01_phase6_v2_1_v2_e3_pilots_audit.json`

审计包含运行/远端 tree 等价关系、环境与组件指纹、3/9/54 计数、9 组目标和计时中位数、三个 run 的四类制品哈希、全局 registry/projection 哈希、family 前序状态与停止边界。大型原始输出继续保留在 D 盘且不提交。

## 验证结果

```text
.venv-gurobi\Scripts\python.exe -m pytest -q tests\test_phase6_v2_e3_pilot_audit.py
1 passed in 0.07s

.venv-gurobi\Scripts\python.exe -m pytest -q
129 passed in 28.28s

.venv-gurobi\Scripts\python.exe -m compileall -q src tests
passed

git diff --check
passed
```

最终验证 CI run `30696021947`：success（普通回归 `123 passed`，Phase 5 端到端 `6 passed`）。

## 已知限制与停止边界

- V2 pilot 的三次重复是技术重复，不是独立推断样本。
- 本批次只证明当前小规模 V2 配置下的正确性、复现性和计时完整性。
- 未启动 P1、P2 或任何正式种子。
- 本 PR 通过 ChatGPT 复审并由用户手动合并前，不运行 P1 E3 pilot。
- 下一步仅为 P1 E3 pilot：3 个种子 × 3 个预算 × 2 种算法，共 18 次算法执行；完成后才计算 P1 规模推进门槛。

## ChatGPT 审查清单

1. 3/9/54 计数与三次技术重复语义是否正确。
2. 18 个重复组内目标是否一致，冷热目标是否逐预算一致。
3. 是否仅使用 Gurobi 13.0.2、`gurobi_direct`、Threads=1。
4. 三类指纹、环境指纹及执行 tree 是否与合并后的冻结版本一致。
5. 是否不存在失败、超时、补救不可行、重复或诊断重试。
6. 处置字段是否进入结果。
7. E3 投影是否准确由 `3/12` 增至 `6/12`。
8. Family 12/12、30/30 前序结果是否保持有效。
9. 正式授权是否仍为 `false`。
10. 是否没有提交大型输出或提前启动 P1/P2/正式实验。
