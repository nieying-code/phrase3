# Phase 6 v2.1 V1 E3 Pilot Handoff

## 任务目标

在 PR #14 引入相对完全补救、PR #15 重新冻结实验矩阵后，使用当前科学模型和全新运行标识重新执行 V1 E3 pilot。该批次只验证标准 C&CG 冷启动与 SPW-C&CG 热启动在小规模档位上的正确性和一致性，不启动 family、V2、P1、P2 或正式种子。

## 分支和提交

- Branch: `agent/phase6-v2-1-v1-e3-pilots`
- Remote merged base: `bdf016ba4ed537aa25950f6e3924d68cdb5b81c1`（PR #15 merge commit）
- Local base/head tree: `e15526efe9ecbb350c41eb25cfb797153c24749e`
- Commit SHA: pending
- Draft PR: pending
- CI: pending

由于执行开始时 Git HTTPS 连接被重置，本地分支从已合并 PR #15 的 head `977675e27f2de0f48ec51a60e349dc2a77165ee0` 创建。GitHub API 独立核验表明，该提交是远端 merge commit 的第二父提交，且两者 tree SHA 完全相同。发布前仍需重新同步远端状态。

## 干净运行基线

本批次使用独立输出根目录：

`outputs/phase6_v21_rr_clean`

该目录在运行前不存在，因此当前指纹的 E3 投影严格从 `0/12` 开始。旧 V1、旧 family pilot，以及因执行顺序误判而提前产生的 E1/E2/E4 记录，均保留在原输出目录作为审计证据，但不会进入本批次 registry、projection 或完成率。

基线核验结果：

| 项目 | 值 |
|---|---|
| Matrix status | `frozen_for_formal_execution` |
| Scientific config SHA-256 | `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3` |
| E3 component SHA-256 | `7713671bab67eec8d99fdf776f1d645740d09d020ef31b55513ccc80595f951f` |
| Family component SHA-256 | `5803afd60d39a2e982d9b2c879453ef2d4e21755fcb46791810a1e1de8e5076f` |
| Python | `3.12.10` |
| Gurobi Optimizer / gurobipy | `13.0.2 / 13.0.2` |
| Pyomo interface | `gurobi_direct` |
| Threads | `1` |
| Initial E3 coverage | `0/12` |
| Initial formal authorization | `false` |

## 执行范围

V1 参数：1 种物资、6 期、50 个训练场景、预算系数 `0.90/1.10/1.30`。三个 pilot 种子均执行标准 C&CG 冷启动和 SPW-C&CG 热启动，每个算法仅一次计时重复。

有效 primary run：

- `pilot_rr_v21_e3_v1_primary_2026072001`
- `pilot_rr_v21_e3_v1_primary_2026072002`
- `pilot_rr_v21_e3_v1_primary_2026072003`

## 数值结果

| Seed | Budget factor | Budget | Cold objective | Warm objective | Difference | Cold/Warm iterations |
|---:|---:|---:|---:|---:|---:|---:|
| 2026072001 | 0.90 | 1107.289385 | 30620.790291 | 30620.790291 | 0.0 | 1 / 1 |
| 2026072001 | 1.10 | 1353.353693 | 25431.602136 | 25431.602136 | 0.0 | 1 / 1 |
| 2026072001 | 1.30 | 1599.418001 | 20301.417127 | 20301.417127 | 0.0 | 1 / 1 |
| 2026072002 | 0.90 | 1107.289385 | 17728.740006 | 17728.740006 | 0.0 | 1 / 1 |
| 2026072002 | 1.10 | 1353.353693 | 12593.369450 | 12593.369450 | 0.0 | 1 / 1 |
| 2026072002 | 1.30 | 1599.418001 | 7468.893507 | 7468.893507 | 0.0 | 1 / 1 |
| 2026072003 | 0.90 | 1107.289385 | 21611.625138 | 21611.625138 | 0.0 | 1 / 1 |
| 2026072003 | 1.10 | 1353.353693 | 16465.082639 | 16465.082639 | 0.0 | 1 / 1 |
| 2026072003 | 1.30 | 1599.418001 | 11336.058725 | 11336.058725 | 0.0 | 2 / 2 |

汇总：

- `3/3` primary runs 为 `optimal`；
- `9/9` 冷热预算配对为 `optimal`；
- `18/18` 算法执行为 `optimal`；
- 最大绝对目标差为 `0.0`；
- 无 solver failure、timeout、父运行或重复 primary；
- 算法执行时间合计 `27.7724 s`，中位数 `1.4969 s`，最大值 `2.0613 s`；
- 峰值内存最大值 `75.1445 MB`；
- 冷热迭代数合计 `20`；
- `early_disposal`、`expired_waste`、`total_disposal` 三个字段在三个主结果中均存在；
- 未发现 `unexpected_infeasible_recourse`。

## 投影状态

V1 完成后的 E3 投影为：

- `completed_run_count = 3`；
- `required_run_count = 12`；
- `primary_completion_rate = 0.25`；
- `failed_primary_runs = []`；
- `duplicate_primary_runs = []`；
- `formal_execution_authorized = false`。

该状态符合流程：本批次只完成 V1，不能启动正式种子。

## 验证结果

```text
.venv-gurobi\Scripts\python.exe -m pytest -q
126 passed in 38.85s

.venv-gurobi\Scripts\python.exe -m compileall -q src tests
passed
```

大型 `result.json` 和 `checkpoint.json` 没有通过 PowerShell 完整加载或输出；运行监控只读取有界 `status_summary.json`、小型 CSV 和文件元数据。原始实验输出继续由 Git 忽略，不进入 PR。

## 已知限制与停止边界

- V1 仅为正确性 pilot，不用于显著性推断。
- 本批次没有运行 family、V2、P1、P2 或正式种子。
- 本 PR 通过 ChatGPT 复审并由用户手动合并前，不得启动 family pilot。
- 合并后应使用同一干净输出根目录，按每个种子的 `E1 → E2 → E4 → E5` 顺序重新运行 family pilot。

## ChatGPT 审查清单

1. 三个 run 是否均属于当前科学配置、E3 和环境指纹。
2. 是否恰好存在 3 个 V1 primary、9 个预算配对和 18 个算法执行。
3. 冷热目标、状态、迭代与预算是否逐项一致。
4. 相对完全补救新增的三个处置字段是否进入正式结果。
5. 是否不存在失败、重复 primary、旧指纹或父运行混入。
6. 投影是否正确停留在 `3/12` 且正式授权为 `false`。
7. 提前运行的 family 记录是否通过独立输出根目录与本批次完全隔离。
8. 是否没有提交大型实验输出或提前启动下一批实验。
