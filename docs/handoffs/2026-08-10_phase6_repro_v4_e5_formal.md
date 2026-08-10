# Phase 6 Reproducibility-v4 E5 Formal Handoff

## 任务目标

在 E4 正式结果经 PR #36 复审并合并、用户单独授权后，执行冻结精简矩阵的 E5 正式敏感性实验。本批仅运行 E5：前 5 个 V2 正式训练种子、预算系数 1.10、11 个唯一 OFAT 配置和 4 个库存—供应交互配置，共 75 个内生储备模型工作单元。完成后立即停止，未启动 E3 或其他正式实验族。

## 分支和执行基线

- Branch: `results/phase6-repro-v4-e5-formal`
- Execution and merged-main commit: `54d6ed0868b0ba47b3e7886714a75ab85f911084`
- Execution and merged-main tree: `03216fc7c4d0de155c7770f652e8a5dd816fcf4a`
- Draft PR: https://github.com/nieying-code/phrase3/pull/37
- 启动时 tracked 修改为 0、未跟踪执行输入为 0、工作树干净。
- 受控读写根目录：`outputs/phase6_v21_repro_v3/`。

## 环境与授权

- Matrix: `frozen_for_formal_execution`
- Scientific config: `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3`
- Family runner: `983776a19e0a12937bc8a185b0fe5fdf76877d266445dcfce5f252d397a6ca8c`
- Family component: `92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e`
- Environment: `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`
- Python 3.12.10；Gurobi/gurobipy 13.0.2；Pyomo `gurobi_direct`；`Threads=1`；无 HiGHS 或求解器回退。
- 启动前投影为 `passed`，`compute_gate_passed=true`，`formal_execution_authorized=true`。

## 正式设计

每个正式训练种子运行以下 15 个配置：

- 基准配置 1 个；
- OFAT：需求变异系数 0.15/0.45、应急价格加价均值 0.15/0.55、供应缩减均值 0.05/0.40、保质期 1/6、仓储容量系数 0.5/1.5，加上唯一基准后共 11 个 OFAT 配置；
- 交互：保质期 1/6 × 供应缩减均值 0.05/0.40，共 4 个配置。

因此：`5 个种子 × 15 个配置 = 75` 个工作单元。预算固定为 `1.10 × B_ref = 1353.3536929340091`。

## 执行结果

- 5/5 primary runs 为 `optimal`；
- 75/75 工作单元为 `optimal`；
- 无失败、超时、重复、parent run 或 diagnostic retry；
- 5 条 run 墙钟合计 `177.00260489969514 s`；单条最大 `36.304952499922365 s`；峰值内存最大 `122.859375 MB`。

执行过程中，承载前五条串行命令的外层观察窗口在 120 秒时结束。此时前四条已完整最终化，第五条尚未创建目录、checkpoint 或 registry 记录。核验无残留后，第五条按原计划 run ID 首次启动并成功；没有覆盖或重试任何已开始的 run，属于观察器边界事件而非科学失败。

## 内生储备机制结果

冻结 E5 范围内的 75 个方案全部得到：

```text
R = 0
reserve_ratio = 0
positive_reserve_plan_count = 0 / 75
configuration_count_with_any_positive_reserve = 0 / 15
```

因此，本批没有找到使内生储备转为正值的风险、成本或库存配置。基准平均鲁棒目标为 `21361.054897160313`。主要描述性变化为：

| 配置 | 五种子平均鲁棒目标 | 相对基准平均差 |
|---|---:|---:|
| demand CV = 0.15 | 8406.402085 | -12954.652812 |
| demand CV = 0.45 | 36949.909617 | +15588.854720 |
| emergency markup mean = 0.15 | 19137.976986 | -2223.077912 |
| emergency markup mean = 0.55 | 23584.132809 | +2223.077912 |
| shelf life = 1 | 21790.102837 | +429.047940 |
| storage factor = 0.5 | 21699.337088 | +338.282191 |
| storage factor = 1.5 | 21521.592213 | +160.537316 |

应急价格加价敏感性必须按联动校准解释。冻结矩阵把物资缺货惩罚定义为：

```text
shortage_penalty
= shortage_penalty_multiplier
  × maximum_regular_price
  × (1 + emergency_price_markup_mean + 3 × emergency_price_markup_sd)
```

因此，加价均值 0.15、0.35 和 0.55 对应的缺货惩罚分别为 `39.99938438763306`、`44.9993074360872` 和 `49.99923048454133`。本批识别的是“应急价格加价均值—缺货惩罚联动校准对鲁棒目标具有明显影响”，不是保持缺货惩罚不变的纯应急价格 OFAT，无法分离价格效应与惩罚效应。

75 个方案的储备金均为 0。公共补救约束为 `sum(emergency_price × emergency_purchase) <= R`，应急采购非负且应急价格严格为正，所以每个配置的应急支出和应急采购量在结构上均只能为 0。E5 worker 结果没有直接序列化逐期应急采购，本结论的证据类型是锁定的零储备结果与公共补救约束共同蕴含的结构证明；机器审计对此作了明确区分。

供应缩减均值 0.05/0.40 在本批与基准目标相同；四个交互配置的供应维度也未改变对应保质期结果。这是 `R=0`、应急采购未被使用时的条件性结果，不表示供应风险一般无关。

## 科学解释与论文边界

本批支持以下结论：

1. 内生储备是由模型决定而非外部固定的机制，代码和求解流程能够一致求解不同风险配置；
2. 在当前冻结 V2 预算、成本和风险范围内，最优机制稳定选择零储备；
3. 当前结果不支持“内生储备在基准或敏感性范围内产生正储备并优于固定比例策略”的经验主张；
4. 论文仍可把内生储备作为建模机制贡献，但必须把零激活作为正式结果如实报告，不能宣称经验优势；
5. 若论文必须展示正储备激活区间，需要另行提出、冻结和复审扩展实验设计，不能事后从本批选择参数或静默扩大范围。

在决定是否增加扩展机制实验前，应重点审查：常规采购在所有时期的确定性可得性、常规与应急采购相对价格、储备的机会成本、缺货惩罚、预算范围，以及需求—供应—价格联合极端程度。这些是研究设计问题，不在本结果 PR 内修改。

## 制品与机器审计

机器审计文件：`docs/handoffs/2026-08-10_phase6_repro_v4_e5_formal_audit.json`。它精确锁定：

- 5 条 run 的 result、manifest、status-summary 哈希；
- 每条 run 的 15-plan 身份摘要和 worker-result 映射摘要；
- 完整 `5 × 15` 笛卡尔积；
- 15 个配置的储备激活数、目标均值、范围和基准配对差；
- 三档加价均值对应的缺货惩罚、向量哈希以及价格—惩罚联动解释；
- 由零储备与公共应急预算约束推出的逐配置零应急支出证据；
- 外层观察窗口事件、全局 registry/projection 哈希和停止边界。

大型原始 worker 结果和日志仅保留在 D 盘受控输出根目录，不提交 GitHub。

## 验证

执行：

```text
.venv-gurobi\Scripts\python.exe -m pytest -q tests\test_phase6_repro_v4_e5_formal_audit.py
.venv-gurobi\Scripts\python.exe -m pytest -q
.venv-gurobi\Scripts\python.exe -m compileall -q src tests
git diff --check
```

实际结果：专项审计 `1 passed`，完整本地回归 `168 passed`，`compileall` 与 `git diff --check` 均通过。本次解释修复没有生成场景、调用 Gurobi 或重新运行 E5。

## 已知限制

- E5 只有 5 个训练种子，属于有限敏感性证据；
- 只考察冻结的 1.10 预算系数和 15 个配置；
- OFAT 不能识别未列入矩阵的高阶交互；
- 本批没有正储备方案，无法估计储备激活阈值；
- 真实数据校准仍属于后续独立轨道。

## 停止边界与下一步

E5 完成后已停止，没有启动 E3。应先由 ChatGPT 复审本 PR 并由用户手动合并。之后需由用户决定：按原冻结计划继续 E3 算法正式实验，或先对“零储备全范围”进行研究设计评估；任何新增科学参数范围都必须通过新的受审矩阵修订和相应门槛，不能直接追加运行。

## ChatGPT 审查清单

1. 5 个种子 × 15 个配置是否形成 75 个唯一工作单元；
2. 11 个 OFAT 与 4 个交互配置是否与冻结矩阵一致；
3. 75/75 是否全部最优且无失败、重复或诊断运行；
4. 每条 run 和 worker 映射哈希是否被精确锁定；
5. 75 个方案的储备金是否确实全部为 0；
6. 配置目标均值与基准配对差是否可由审计复核；
7. 供应风险无效的表述是否严格限定在零储备条件下；
8. 应急加价敏感性是否明确表述为与缺货惩罚联动，而非纯价格效应；
9. 零应急采购是否由零储备和公共应急预算约束严格推出；
10. 是否避免把机制内生性夸大为正储备激活或经验优势；
11. 外层观察窗口事件是否未造成覆盖、重试或科学失败；
12. E3 是否确实未启动。
