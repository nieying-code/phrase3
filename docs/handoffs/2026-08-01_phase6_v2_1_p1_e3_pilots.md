# Phase 6 v2.1 P1 E3 Pilot Handoff

## 任务目标

在 V2 E3 pilot 通过复审并合并后，使用冻结矩阵运行 P1 E3 pilot，验证三物资、十二期、500 训练场景档位的冷/热算法一致性、运行时间和资源需求。本批次完成后立即停止，评估 P1 pilot 到 P2 pilot 的规模推进条件，不启动 P2 或正式种子。

## 分支和提交

- Branch: `agent/phase6-v2-1-p1-e3-pilots`
- Base/execution SHA: `9c135f7120ad322302bc2db868f2c77e260e49af`（PR #18 merge commit）
- Execution tree: `91bb61b768345fab833861b0f32a3f9a21dd1162`
- Validated results commit: `b1706fa2d59a0baa8a1d13815187b157d865381b`
- Draft PR: https://github.com/nieying-code/phrase3/pull/19
- Results CI: https://github.com/nieying-code/phrase3/actions/runs/30697544132 (`124 passed + 6 passed`)

## 环境与前序状态

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
| Initial E3 coverage | `6/12` |
| Family prerequisites | `12/12 runs, 30/30 work units, all optimal` |
| Formal authorization | `false` |

输出根目录为 `outputs/phase6_v21_rr_clean`。执行前已跟踪文件修改数为 0；该目录作为受控读写根目录读取已批准的 V1、V2 和 family 前序 registry/projection 制品，并写入 P1 结果。三个其他历史输出目录没有作为输入，不存在未提交模型、矩阵、runner 配置或依赖锁参与执行。

## 执行范围

严格串行运行：

- `pilot_rr_v21_e3_p1_primary_2026072001`
- `pilot_rr_v21_e3_p1_primary_2026072002`
- `pilot_rr_v21_e3_p1_primary_2026072003`

每条 run 包含三个预算、标准 C&CG 冷启动和 SPW-C&CG 热启动，各一次计时：

```text
3 seeds × 3 budgets × 2 algorithms = 18 executions
```

## 数值结果

| Seed | Budget factor | Cold objective | Warm objective | Difference | Cold/Warm seconds | Iterations |
|---:|---:|---:|---:|---:|---:|---:|
| 2026072001 | 0.90 | 142202.125596 | 142202.125596 | 0.0 | 18.3612 / 18.5115 | 1 / 1 |
| 2026072001 | 1.10 | 114878.481607 | 114878.481607 | 0.0 | 18.5907 / 18.6162 | 1 / 1 |
| 2026072001 | 1.30 | 87703.878601 | 87703.878601 | 0.0 | 18.7940 / 18.6469 | 1 / 1 |
| 2026072002 | 0.90 | 169541.956665 | 169541.956665 | 0.0 | 18.3695 / 18.2590 | 1 / 1 |
| 2026072002 | 1.10 | 142115.683286 | 142115.683286 | 0.0 | 18.3085 / 18.7679 | 1 / 1 |
| 2026072002 | 1.30 | 114842.175537 | 114842.175537 | 0.0 | 57.5367 / 57.5343 | 3 / 3 |
| 2026072003 | 0.90 | 175100.034736 | 175100.034736 | 0.0 | 18.0519 / 17.1772 | 1 / 1 |
| 2026072003 | 1.10 | 147658.739492 | 147658.739492 | 0.0 | 16.6230 / 16.0551 | 1 / 1 |
| 2026072003 | 1.30 | 120356.223834 | 120356.223834 | 0.0 | 17.6548 / 15.9818 | 1 / 1 |

汇总：3/3 primary、9/9配对、18/18算法执行均为 `optimal`；最大冷热目标差 `0.0`；峰值内存 `124.929688 MB`；不存在补救不可行、solver failure、timeout、重复、parent run 或 diagnostic retry；三个处置字段完整。

## P1 Pilot 规模推进评估

依照冻结矩阵公式，对 P1 pilot 计算用于“是否允许进入 P2 pilot 复审”的推进证据：

| 指标 | 实测 | 门槛 | 结果 |
|---|---:|---:|---|
| 联合完成率 | 1.000000 | ≥ 0.80 | 通过 |
| 冷启动中位运行时间比例 | 0.010201 | — | — |
| 热启动中位运行时间比例 | 0.010284 | — | — |
| 最大算法中位运行时间比例 | 0.010284 | ≤ 0.75 | 通过 |

因此 P1 pilot 的人工受审推进评估为 `passed`。

需要严格区分：代码中的 canonical `scale_advancement.json` 明确只由正式 P1 runs 生成，并用于阻止或允许正式 P2。当前不能用 pilot rows 伪造该正式文件，否则会错误授权正式 P2。因此本 PR 将 pilot 推进结论保存在紧凑审计中，等待 ChatGPT 和用户明确授权 P2 pilot；canonical formal gate 仍未创建。

## 当前投影与停止边界

- E3 coverage: `9/12`
- Projection status: `insufficient_pilot_coverage`
- Failed/duplicate/diagnostic: `0/0/0`
- `compute_gate_passed=false`
- `formal_execution_authorized=false`
- P2 未启动
- 正式种子未启动

## 机器审计

`docs/handoffs/2026-08-01_phase6_v2_1_p1_e3_pilots_audit.json` 记录3/9/18计数、逐预算目标和时间、运行制品哈希、指纹、projection 哈希、pilot 推进公式和停止边界。大型输出保留在 D 盘，不提交。

## 验证结果

```text
.venv-gurobi\Scripts\python.exe -m pytest -q tests\test_phase6_p1_e3_pilot_audit.py
1 passed in 0.07s

.venv-gurobi\Scripts\python.exe -m pytest -q
130 passed in 28.35s

.venv-gurobi\Scripts\python.exe -m compileall -q src tests
passed

git diff --check
passed
```

CI run `30697544132`：success（普通回归 `124 passed`，Phase 5 端到端 `6 passed`）。

## 下一步与审查清单

PR 通过复审并由用户手动合并前，不运行 P2。审查者应重点确认：

1. 3/9/18计数、串行顺序和全最优状态；
2. 冷热目标逐预算一致；
3. Gurobi 13.0.2、`gurobi_direct`、Threads=1；
4. P1 pilot 规模推进公式和两个门槛方向；
5. pilot 推进评估与 canonical formal gate 的范围区分；
6. E3准确为9/12，正式授权仍为false；
7. P2和正式种子均未启动；
8. 没有大型输出或科学代码变更进入 PR。
