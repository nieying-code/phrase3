# Phase 6 v2.1 E1 Formal Exactness Handoff

## 任务目标

在 Phase 6 全部 pilot 与计算门槛通过、PR #20 合并且用户明确授权批次一后，
执行 E1 正式正确性实验。E1 对 D0、V1、V2 的全部冻结正式计划逐一比较
全场景扩展式模型与标准 C&CG，并通过独立补救模型重新评价两种第一阶段方案。
本批次完成后立即停止，没有启动 E2、E3、E4 或 E5 正式实验。

## 分支和提交

- Branch: `agent/phase6-formal-e1`
- Base/execution SHA: `f169f2d783cf4714e8fffcadb92de1e2930c46bb`
- Execution tree: `0f945a31596af01ca168375682714002c8a72a2c`
- Validated result commit: `pending`
- Draft PR: `pending`
- CI: `pending`

## 环境和执行边界

| 项目 | 值 |
|---|---|
| Matrix status | `frozen_for_formal_execution` |
| Scientific config SHA-256 | `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3` |
| Family config SHA-256 | `983776a19e0a12937bc8a185b0fe5fdf76877d266445dcfce5f252d397a6ca8c` |
| Family component SHA-256 | `5803afd60d39a2e982d9b2c879453ef2d4e21755fcb46791810a1e1de8e5076f` |
| Environment SHA-256 | `0306c49cf953a79e3ade0fdf537e074dd17ddb942677333c62ef3f1bfb4782c2` |
| Python | `3.12.10` |
| Gurobi / gurobipy | `13.0.2 / 13.0.2` |
| Pyomo / interface / threads | `6.10.1 / gurobi_direct / 1` |
| HiGHS fallback | `false` |

执行前 tracked 修改数为 0。manifest 的 `working_tree_dirty=true` 仅来自未跟踪
实验输出目录；不存在未提交模型、矩阵、runner 配置或依赖锁输入。

## 正式执行范围

严格串行执行：

| Tier | Seeds | Budgets per seed | Runs | Work units |
|---|---|---:|---:|---:|
| D0 | `20260723` | 6 个历史预算 | 1 | 6 |
| V1 | `2026072401–2026072403` | 3 | 3 | 9 |
| V2 | `2026072401–2026072410` | 3 | 10 | 30 |
| Total | — | — | 14 | 45 |

每个工作单元分别执行一个扩展式模型和一个标准 C&CG，因此共 45 次扩展式、
45 次标准 C&CG，即 90 次模型/算法执行。

## 验收结果

- 14/14 primary runs 为 `optimal`；
- 45/45 工作单元完成；
- 扩展式与标准 C&CG 最大目标差：`5.456968e-12`；
- 两种方法最大储备金差：`5.684342e-14`；
- 最大标准 C&CG 迭代次数：4；
- 最大最终场景池规模：6；
- 90 个独立精确评价块全部为 `optimal`；
- 精确补救场景总数：7140；
- `infeasible_recourse=0`；
- `solver_failure=0`；
- 峰值内存：`121.1875 MB`；
- 14 条 family run 墙钟时间之和：`165.6254 s`。

分档结果：

| Tier | Work units | Exact scenarios | Max objective difference |
|---|---:|---:|---:|
| D0 | 6 | 240 | `1.364242e-12` |
| V1 | 9 | 900 | `0.0` |
| V2 | 30 | 6000 | `5.456968e-12` |

所有目标差均远低于各计划的冻结容差。没有 timeout、失败 primary、重复 run、
parent run 或 diagnostic retry。

## 制品完整性

机器审计文件
`docs/handoffs/2026-08-01_phase6_v2_1_e1_formal_audit.json` 记录：

- 14 条 run 的 result、manifest 与 status-summary SHA-256；
- D0/V1/V2 数量和精确评价汇总；
- 目标、储备金、迭代和内存一致性；
- family result 与 manifest 交叉验证；
- family result 所登记的全部 worker result 哈希复核；
- 科学、配置、组件和环境指纹；
- E2/E3/E4/E5 均未启动的停止边界。

大型结果、训练场景、worker 文件和日志继续只保留在 D 盘，不进入 Git。

## 验证结果

```text
.venv-gurobi\Scripts\python.exe -m pytest -q tests\test_phase6_e1_formal_audit.py
1 passed in 0.04s

.venv-gurobi\Scripts\python.exe -m pytest -q
132 passed in 27.92s

.venv-gurobi\Scripts\python.exe -m compileall -q src tests
passed

git diff --check
passed
```

## 下一步与审查清单

本 PR 通过 ChatGPT 复审并由用户手动合并前，不启动 E2。审查者应确认：

1. D0/V1/V2 的 1/3/10 条正式 run 和 6/9/30 工作单元；
2. 扩展式与标准 C&CG 目标在冻结容差内一致；
3. 两种方案均经过独立完整场景补救评价；
4. 7140 个补救场景全部最优、无相对完全补救违例；
5. Gurobi 13.0.2、`gurobi_direct`、Threads=1 且无回退；
6. result、manifest、registry 和 worker 制品哈希闭环；
7. PR 未提交大型结果或修改科学代码；
8. E2 及其他正式实验确实未启动。

复审和手动合并后，下一批才是 E2 六策略正式比较。
