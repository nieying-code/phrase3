# Phase 6 Reproducibility-v4 E1 Formal Handoff

## 任务目标

在 PR #33 合并后的最终受审基线上，执行 Phase 6 第一批正式实验 E1，验证全场景扩展式模型与标准 C&CG 在 D0、V1、V2 全部冻结正式种子和预算上的一致性。批次结束后立即停止，未启动 E2、E3、E4 或 E5 正式实验。

## 分支和提交

- Branch: `results/phase6-repro-v4-e1-formal`
- Execution/base commit: `e6cffb6a65996f5189dd9d6b06845b485da985bc`
- Execution tree: `9880f7c76f3e12bc53f295abc752022c029ec016`
- Results commit: pending
- Draft PR: pending
- CI: pending

## 执行环境和门槛

- Matrix status: `frozen_for_formal_execution`
- Scientific config SHA-256: `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3`
- Family runner SHA-256: `983776a19e0a12937bc8a185b0fe5fdf76877d266445dcfce5f252d397a6ca8c`
- Family component SHA-256: `92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e`
- Environment SHA-256: `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`
- Python: `3.12.10`
- Gurobi/gurobipy: `13.0.2`
- Pyomo/interface/threads: `6.10.1 / gurobi_direct / 1`
- HiGHS fallback: `false`
- Pre-run projection: `passed`; `compute_gate_passed=true`; `formal_execution_authorized=true`

运行开始时已跟踪修改、未跟踪执行输入均为 0，`working_tree_dirty=false`。所有原始输出只写入 D 盘受控根目录 `outputs/phase6_v21_repro_v3/`，没有读取该根目录之外的历史输出。

## 正式执行范围

| Tier | Seeds | Runs | Work units |
|---|---|---:|---:|
| D0 | `20260723` | 1 | 6 |
| V1 | `2026072401`–`2026072403` | 3 | 9 |
| V2 | `2026072401`–`2026072410` | 10 | 30 |
| Total | — | 14 | 45 |

每个工作单元分别求解一次全场景扩展式模型和一次标准 C&CG，因此共 45 次扩展式、45 次标准 C&CG，即 90 次模型/算法执行。14 条 primary run 严格串行，均使用全新 run ID。

## 验收结果

- 14/14 primary runs 为 `optimal`；
- 45/45 工作单元完成；
- 90/90 模型/算法执行成功；
- 7,140 次独立精确补救评价全部为 `optimal`；
- `infeasible_recourse=0`；
- `solver_failure=0`；
- 扩展式与标准 C&CG 最大目标差：`5.4569682106375694e-12`；
- 最大储备金差：`5.684341886080802e-14`；
- 14 条 run 墙钟时间合计：`155.50782900024205 s`；
- 峰值内存：`121.55078125 MB`；
- 批次结束后投影仍为 `passed`，正式授权仍为 `true`。

| Tier | Work units | Exact evaluations | Max objective difference |
|---|---:|---:|---:|
| D0 | 6 | 240 | `1.3642420526593924e-12` |
| V1 | 9 | 900 | `0.0` |
| V2 | 30 | 6000 | `5.4569682106375694e-12` |

所有目标差均小于各工作单元的冻结容差；没有失败 primary、重复 primary、parent run 或 diagnostic retry。

## 机器审计

紧凑审计文件为 `docs/handoffs/2026-08-10_phase6_repro_v4_e1_formal_audit.json`，记录：

- 执行 commit、tree、四类批准指纹与环境；
- 14 条 run 的 result、manifest、status-summary SHA-256；
- 14/45/90/7140 数量闭合；
- tier、种子、formal 模式和无父运行关系；
- 全局 registry、performance 和 projection 文件哈希；
- 数值一致性、制品交叉验证和停止边界。

大型结果、worker结果、训练场景与日志继续只保留在 D 盘，不进入 Git。

## 验证命令

```text
.venv-gurobi\Scripts\python.exe -m pytest -q tests\test_phase6_repro_v4_e1_formal_audit.py
.venv-gurobi\Scripts\python.exe -m pytest -q
.venv-gurobi\Scripts\python.exe -m compileall -q src tests
git diff --check
```

实际本地结果：专项审计 `1 passed in 0.03s`；完整回归
`165 passed in 37.75s`；语法检查和 `git diff --check` 均通过。
GitHub Actions 状态将在 Draft PR 创建后补充。

## 停止边界和下一步

本批次未启动 E2、E3、E4 或 E5。PR 通过 ChatGPT 复审并由用户手动合并前，不得启动下一批正式实验。若 E1 结果获批，下一批建议为 E2 六策略正式比较，但必须由用户再次明确授权。

## ChatGPT 审查清单

1. D0/V1/V2 的 1/3/10 条正式 run 与 6/9/30 工作单元是否闭合；
2. 45 次扩展式与 45 次标准 C&CG 是否均成功；
3. 两类模型是否都经过完整训练场景的独立精确补救评价；
4. 7,140 次补救评价是否均最优且不存在相对完全补救违例；
5. 目标差和储备金差是否在冻结容差内；
6. Gurobi 13.0.2、`gurobi_direct`、`Threads=1`及无回退是否成立；
7. result、manifest、registry、worker哈希是否闭环；
8. 是否仅提交紧凑审计和文档，且未启动 E2–E5。
