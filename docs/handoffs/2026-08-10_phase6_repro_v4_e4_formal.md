# Phase 6 Reproducibility-v4 E4 Formal Handoff

## 任务目标

在 E2 正式结果经 PR #35 复审并合并、用户单独授权后，执行 E4 独立样本外精确补救评价。范围为冻结矩阵指定的前 5 个 V2 正式训练种子、按位置配对的 5 个独立测试种子、3 档预算和 6 种策略，共 90 个第一阶段方案与 180,000 次样本外补救评价。批次完成后立即停止，未启动 E3 或 E5。

## 分支与执行基线

- Branch: `results/phase6-repro-v4-e4-formal`
- Execution and merged-main commit: `2161e4182c6e0cd80b54c385b54c5e20048aee7f`
- Execution and merged-main tree: `7e5f15a3a2637b860d7dde9447d3dff13c8f1b11`
- Results documentation commit: `3084288`
- Draft PR: https://github.com/nieying-code/phrase3/pull/36
- Results CI: https://github.com/nieying-code/phrase3/actions/runs/31362367642
  (`success`; Linux and Windows jobs passed)
- 启动时已跟踪修改为 0、未跟踪执行输入为 0、工作树干净。
- 受控读写根目录为 `outputs/phase6_v21_repro_v3/`；E4 只读取其中经哈希验证的 E2 来源方案，未读取外部历史输出目录。

## 环境与授权

- Matrix: `frozen_for_formal_execution`
- Scientific config: `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3`
- Family runner: `983776a19e0a12937bc8a185b0fe5fdf76877d266445dcfce5f252d397a6ca8c`
- Family component: `92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e`
- Environment: `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`
- Python 3.12.10；Gurobi/gurobipy 13.0.2；Pyomo `gurobi_direct`；`Threads=1`；无求解器回退。
- 启动前和每条正式 run 最终化后，投影均保持 `passed`、`compute_gate_passed=true`、`formal_execution_authorized=true`。

## 正式实验设计

训练种子 `2026072401`–`2026072405` 分别与测试种子 `2026082401`–`2026082405` 按列表位置配对。每个训练种子运行 3 档预算和以下 6 种 E2 第一阶段策略：确定性均值、零储备、固定 10%/30%/50% 储备、内生储备。测试集禁止重新优化第一阶段方案；同一训练—测试种子对内的全部策略共享同一 2,000 场景测试集。

```text
5 个训练—测试种子对 × 3 档预算 × 6 种策略 = 90 个方案
90 个方案 × 2,000 个独立测试场景 = 180,000 次补救评价
```

## 验收结果

- 5/5 primary runs 为 `optimal`；
- 90/90 工作单元完成；
- 180,000/180,000 次样本外补救评价为 `optimal`；
- `infeasible_recourse=0`，`solver_failure=0`；
- 无失败、重复、parent run 或 diagnostic retry；
- `total_disposal = early_disposal + expired_waste`，`waste = total_disposal`，全部 90 个方案的聚合恒等式误差均为 0；
- 5 条 run 墙钟合计 `2745.698771599913 s`，单条最大 `553.6301838001236 s`，峰值内存最大 `97.3984375 MB`。

## 样本外描述性结果

以下为 15 个“训练种子—预算”方案的策略均值，仅作为冻结矩阵定义的有限描述性样本外证据：

| 策略 | 平均成本 | P95 | CVaR95 | 服务水平 | 缺货概率 |
|---|---:|---:|---:|---:|---:|
| deterministic_mean | 3531.578 | 11388.043 | 15899.231 | 0.9151 | 0.4344 |
| zero_reserve | 7191.076 | 14186.645 | 17559.237 | 0.7856 | 0.8890 |
| fixed_reserve_0_10 | 6144.478 | 13979.433 | 17630.842 | 0.8232 | 0.8102 |
| fixed_reserve_0_30 | 5321.254 | 14221.393 | 18292.365 | 0.8512 | 0.6265 |
| fixed_reserve_0_50 | 4753.581 | 14654.461 | 19238.133 | 0.8687 | 0.5266 |
| endogenous_reserve | 7191.076 | 14186.645 | 17559.237 | 0.7856 | 0.8890 |

由于 E2 中内生方案与零储备方案具有相同的第一阶段决策，E4 的 15 个逐组配对在平均成本、P95、CVaR95、服务水平和缺货概率上全部完全一致，最大绝对差为 0。这确认了零储备训练解的样本外表现与对应零储备策略一致，但并不证明零储备在样本外占优。

相反，在本次冻结测试分布上，固定比例储备相较零储备呈现更低的平均成本和更高的服务水平；确定性均值方案的描述性均值表现最好。该结果可能反映训练鲁棒目标、冻结测试分布与策略保守性之间的差异，只能作为配对效应和尾部风险轮廓报告，不能以 5 个训练种子作强显著性或普遍性结论。E5 将进一步检验成本、需求与供应风险变化下内生储备是否转为正值。

## 制品与机器审计

机器审计文件 `docs/handoffs/2026-08-10_phase6_repro_v4_e4_formal_audit.json` 精确锁定：

- 5 条 run 的 result、manifest、status-summary 哈希；
- 每条 run 的 18-plan 身份摘要、worker 映射摘要及 E2 来源方案—哈希映射摘要；
- 完整 `5 × 3 × 6` 笛卡尔积、180,000 场景计数和五类种子配对；
- 内生与零储备的 15 组逐组比较摘要；
- 处置量恒等式、全局 registry/projection 哈希及停止边界。

大型场景、worker 结果和求解日志仅保留在 D 盘受控输出根目录，不提交 GitHub。

## 验证

```text
.venv-gurobi\Scripts\python.exe -m pytest -q tests\test_phase6_repro_v4_e4_formal_audit.py
.venv-gurobi\Scripts\python.exe -m pytest -q
.venv-gurobi\Scripts\python.exe -m compileall -q src tests
git diff --check
```

实际结果：专项审计 `1 passed in 0.09s`；完整回归 `167 passed in 40.55s`；
`compileall` 和 `git diff --check` 通过。没有重新运行 E4；以上验证只检查紧凑审计、代码回归和语法。

## 已知限制与论文边界

- E4 只有 5 个独立训练种子，定位为有限描述性证据；
- 2,000 个测试场景提高单方案尾部指标精度，但不能替代训练种子这一独立统计单位；
- 禁止把 90 个方案、预算或测试场景当成 90/180,000 个独立训练样本；
- 本批结果没有回答何种参数条件会激活正内生储备，该问题留给 E5；
- 真实数据校准仍属于后续独立轨道。

## 停止边界与下一步

本批次没有启动 E3 或 E5。结果 PR 经 ChatGPT 复审并由用户手动合并前，不得启动下一批正式实验。后续批次必须由用户重新明确授权。

## ChatGPT 审查清单

1. 5 个训练种子、5 个独立测试种子、3 预算、6 策略是否形成 90 个唯一方案；
2. E4 是否逐方案验证唯一的 E2 来源方案及其哈希，且未在测试集重优化；
3. 180,000 次补救评价是否全部最优，无不可行或求解失败；
4. 内生与零储备的 15 个逐组配对是否完全一致；
5. 策略均值是否仅作描述性结果，未形成强显著性主张；
6. 处置量、服务水平、尾部成本和状态计数定义是否符合冻结矩阵；
7. 5 条 run 及 90 个 worker 的身份和制品哈希是否完整锁定；
8. 是否严格使用 Gurobi 13.0.2、`gurobi_direct`、`Threads=1`；
9. E3 和 E5 是否确实未启动。
