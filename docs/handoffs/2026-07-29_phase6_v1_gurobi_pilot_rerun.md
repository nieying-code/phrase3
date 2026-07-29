# Phase 6 V1 Gurobi Pilot Rerun Handoff

## 任务目标

在 PR #8 修复 Windows 心跳文件瞬时锁问题并合并后，使用精简版 Phase 6 实验矩阵，以三个全新 run ID 严格串行重跑 V1 pilot。

本次授权范围仅包含 V1 的三个 pilot 种子。未运行 V2、P1、P2、P3、P4 或任何 formal seed。

## 分支和提交

- Branch: `agent/phase6-v1-gurobi-pilots-rerun`
- Base branch: `main`
- Base commit: `7295d1b14b9a2b90c8686137c032cab5c320565f`
- Results handoff commit: `4474d8d2491721d44b6e04420921593a61dc8bb4`
- PR: [#9](https://github.com/nieying-code/phrase3/pull/9)
- CI: pending

## 固定运行环境

三个 run 均使用仓库内由 PyCharm 配置的项目解释器：

```text
D:\新建文件夹\项目交付\阶段3-4修复同步\phrase3\.venv-gurobi\Scripts\python.exe
```

运行环境：

- Python 3.12.10；
- Pyomo 6.10.1；
- gurobipy 13.0.2；
- Gurobi Optimizer 13.0.2；
- Pyomo接口 `gurobi_direct`；
- `Threads=1`；
- 精确依赖锁验证通过；
- 未启用 HiGHS 或任何求解器回退。

## 执行规则

- 三个 run 严格串行，前一个终态确认后才启动下一个；
- 使用隐藏窗口后台进程；
- 进度检查只读取小型 `status_summary.json`、manifest和CSV；
- 未通过 PowerShell 解析大型 `result.json` 或 `checkpoint.json`；
- 原始 outputs 保留在D盘且不提交Git。

## V1 Pilot结果

### `pilot_v1_postpr8_2026072001`

- Seed: `2026072001`
- Status: `optimal`
- Budget pairs: 3/3 optimal
- Cold/warm executions: 6/6 optimal
- Maximum absolute objective difference: 0.0

### `pilot_v1_postpr8_2026072002`

- Seed: `2026072002`
- Status: `optimal`
- Budget pairs: 3/3 optimal
- Cold/warm executions: 6/6 optimal
- Maximum absolute objective difference: 0.0

### `pilot_v1_postpr8_2026072003`

- Seed: `2026072003`
- Status: `optimal`
- Budget pairs: 3/3 optimal
- Cold/warm executions: 6/6 optimal
- Maximum absolute objective difference: `1.8189894035458565e-12`

该种子是修复前发生 `WinError 5` 的种子。本次完整成功，worker目录无 `*.tmp-*` 临时文件残留，说明 PR #8 的实际运行回归通过。

## 汇总核验

- Run registry：3条目标记录，全部 `optimal`；
- Algorithm performance：18条目标记录，全部 `optimal`；
- Failure registry：0条目标记录；
- 重复 primary run：0；
- 三个run共同指纹：
  - scientific config: `3ac92ff09d85eebd99ba42dfaae54fb4b1ce7171d8e8a5f1bf8bceddb4524745`
  - runner config: `3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd`
  - E3 component: `bce43075dd91053b5b2c4fa2942fa84bea02654be17d2f10c99df08176248342`
- 三个manifest中的完整精确依赖环境一致；
- 峰值内存约为77.2–78.5 MiB；
- V1观测中位吞吐率：
  - 4684.57 master solves/hour；
  - 234228.57 recourse LP solves/hour；
  - 367.87 completed budget pairs/hour。

## 投影和授权状态

当前 pilot projection：

- V1覆盖：3/3；
- 全部要求覆盖：3/12；
- 当前完成率：0.25；
- 缺失：V2、P1、P2各3个种子；
- `compute_gate_passed=false`；
- `status=insufficient_pilot_coverage`；
- `formal_execution_authorized=false`。

E1、E2、E4和E5执行器仍未实现，因此本结果不授权任何正式实验。

## 测试

实际执行：

```text
.\.venv-gurobi\Scripts\python.exe -m pytest -q
```

结果：

```text
83 passed in 35.05s
```

## 修改文件

- `docs/handoffs/2026-07-29_phase6_v1_gurobi_pilot_rerun.md`
  - 记录V1正式pilot重跑证据、指纹、投影状态和下一步边界。

未提交大型实验结果、训练场景、日志或临时文件。

## 已知限制

- 当前只完成V1 pilot；
- 矩阵状态仍为 `candidate_for_freeze_pending_review`；
- 正式种子仍被程序门槛阻止；
- E1、E2、E4、E5执行器与有量纲一致的投影尚未完成；
- 本次结果仅用于V1工程和吞吐量验证，不是论文正式统计结果。

## ChatGPT审查清单

1. 三个run是否均为3/3预算、6/6冷热执行最优；
2. 最大冷热目标差是否在冻结容差内；
3. 三个run是否共享科学配置、runner、E3组件和精确环境；
4. 是否确实使用Gurobi 13.0.2、`gurobi_direct`和单线程；
5. 修复前结果是否被新组件指纹正确排除；
6. 是否存在失败、重复或同run ID重试；
7. `2026072003`是否证明Windows心跳修复通过实际回归；
8. 投影是否保持3/12并禁止正式实验；
9. 是否没有运行未授权档位或正式种子；
10. 原始outputs是否保持在Git之外。

## 下一步建议

1. ChatGPT复审本PR，由用户决定是否合并；
2. 按冻结顺序实现E1、E2、E4和E5执行器及投影；
3. 后续如获明确授权，再使用新分支串行执行V2 pilot；
4. P1通过规模推进门槛后，P2才能运行；
5. 只有全部计算与正式执行门槛通过后才允许formal seeds。
