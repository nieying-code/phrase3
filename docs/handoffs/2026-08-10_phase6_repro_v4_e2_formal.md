# Phase 6 Reproducibility-v4 E2 Formal Handoff

## 任务目标

在 E1 正式结果经 PR #34 复审并合并、用户单独授权后，执行 Phase 6 E2 正式六策略比较。范围为 V2 全部 10 个正式训练种子、3 档预算与 6 种策略，共 180 个正式工作单元。批次结束后立即停止，未启动 E3、E4 或 E5。

## 分支和执行基线

- Branch: `results/phase6-repro-v4-e2-formal`
- Execution commit: `c0d16d3ed8e3912c9350ac1bd16bf5c99b2e43b5`
- Execution tree: `81067a1d35d1495833dca5722845eab0c937e540`
- Merged main commit: `365f835fdde7f25dd79fe29d7581ca5c16b5339d`
- Merged main tree: `81067a1d35d1495833dca5722845eab0c937e540`
- Execution tree equals merged main tree: `true`
- Validated results snapshot commit: `906786cfb886bee5b8092d02e268852446909208`
- Draft PR: https://github.com/nieying-code/phrase3/pull/35
- Results CI: https://github.com/nieying-code/phrase3/actions/runs/31356278451
  (`success`; Linux and Windows jobs passed)

普通 Git HTTPS 在同步时被网络重置，因此执行提交与远程合并提交的 commit SHA 不同；二者 tree 完全相同，说明模型、配置、测试和所有执行字节一致。该等价关系已写入机器审计并由测试精确锁定。

## 环境和授权

- Matrix: `frozen_for_formal_execution`
- Scientific config: `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3`
- Family runner: `983776a19e0a12937bc8a185b0fe5fdf76877d266445dcfce5f252d397a6ca8c`
- Family component: `92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e`
- Environment: `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`
- Python 3.12.10；Gurobi/gurobipy 13.0.2；Pyomo 6.10.1；`gurobi_direct`；`Threads=1`；无求解器回退。
- 启动前投影为 `passed`，`compute_gate_passed=true`，`formal_execution_authorized=true`。
- 启动时工作树干净，未跟踪执行输入为 0，新 run ID 无碰撞。

## 正式实验设计

```text
10个正式种子 × 3档预算 × 6种策略 = 180个工作单元
```

六种策略：确定性均值、零储备、固定10%储备、固定30%储备、固定50%储备、内生储备。每个策略方案均在相同完整训练场景上使用独立补救模型精确重评。

## 验收结果

- 10/10 primary runs 为 `optimal`；
- 180/180 工作单元完成；
- 每种策略恰好 30 个方案；
- 18,000/18,000 次训练场景精确补救评价为 `optimal`；
- `infeasible_recourse=0`；
- `solver_failure=0`；
- 无失败、重复、parent run 或 diagnostic retry；
- 30/30 个“种子×预算”结构比较中，内生储备目标均不差于最佳正固定比例储备；
- `endogenous - best positive fixed`最大值为`-513.8054557105679`，最小值为`-1149.5801370952558`；
- 10条run墙钟合计`445.2149241992738 s`；峰值内存`121.4140625 MB`；
- 批次完成后正式投影和授权保持有效。

本批数据中，内生储备的30个方案均选择`R=0`，其训练鲁棒目标与零储备策略一致。这是当前冻结V2数据和预算组合下的正式结果，不解释为普遍理论结论；后续E4样本外评价与E5敏感性分析将检验其外部表现和参数响应。

## 制品和机器审计

`docs/handoffs/2026-08-10_phase6_repro_v4_e2_formal_audit.json`记录：

- 10条run的result、manifest、status-summary哈希；
- 每条run内18个`plan_id → worker result SHA-256`映射的规范化聚合哈希，共覆盖180个worker结果；
- 10×3×6笛卡尔积、18,000次评价和六策略数量闭合；
- 内生储备结构门槛与策略汇总；
- 执行tree与合并main tree等价关系；
- 全局registry、performance、projection哈希及停止边界。

原始场景、worker结果和日志继续只保留在D盘受控输出根目录，不提交到GitHub。

## 验证

```text
.venv-gurobi\Scripts\python.exe -m pytest -q tests\test_phase6_repro_v4_e2_formal_audit.py
.venv-gurobi\Scripts\python.exe -m pytest -q
.venv-gurobi\Scripts\python.exe -m compileall -q src tests
git diff --check
```

实际本地结果：专项审计`1 passed in 0.05s`；完整回归
`166 passed in 37.97s`；语法检查和`git diff --check`均通过。
GitHub Actions run `31356278451` 对结果快照提交
`906786cfb886bee5b8092d02e268852446909208` 验证成功；Linux和Windows
作业均通过。

## 停止边界和下一步

本批次没有启动 E3、E4 或 E5。该结果PR经ChatGPT复审并由用户手动合并前，不得启动后续正式实验。下一批必须由用户再次明确指定，并保持严格串行和独立停止边界。

## 复审机器审计闭环

PR #35 的复审补充完全基于已最终化的 E2 制品完成，没有重新生成场景或调用求解器。

- 三个预算精确锁定为 `1107.2893851278257`、`1353.3536929340091` 和
  `1599.4180007401926`；六个策略标识也由专项测试逐项锁定。
- 每个正式种子的 18 个排序 plan ID 生成一个 SHA-256 身份摘要；专项测试重新构造
  `10 种子 × 3 预算 × 6 策略` 的完整笛卡尔积并逐条比较十个摘要。
- 已哈希 worker 制品显示：内生方案共 30 个，非零储备方案为 0，最大绝对储备金为 `0.0`。
- 30/30 个内生目标均在冻结绝对容差 `1e-5` 内匹配对应零储备目标。实际观测到的最大绝对
  浮点差为 `5.4569682106375694e-12`，审计如实保留该数值，不将其错误表述为逐位等于零。

## ChatGPT审查清单

1. 10个正式种子、3档预算、6策略是否形成180个工作单元；
2. 每策略是否恰有30个方案并完成完整训练场景精确重评；
3. 18,000次补救评价是否全部最优且无相对完全补救违例；
4. 内生储备是否在30个比较组中不差于最佳正固定比例储备；
5. 10组run级哈希和180个worker映射聚合哈希是否锁定；
6. 执行tree与远程合并main tree是否完全一致；
7. 是否使用Gurobi 13.0.2、`gurobi_direct`、`Threads=1`且无回退；
8. E3–E5是否确实未启动。
