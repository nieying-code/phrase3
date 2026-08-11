# Phase 6 M1 Development Grid Handoff

## 任务目标

在 PR #40 合并后的冻结执行基线上，严格串行运行预注册的 63 组 V1 M1 采购能力开发配置，判断常规采购能力约束是否在排除机械预算剩余和多重最优解后，稳定激活自主应急储备。

## 分支和执行基线

- Branch: `results/phase6-m1-development-grid`
- Base branch: `main`
- PR #40 merge/execution commit: `5c899db05ff8d004d3ca1c90bfa58e30bafe1328`
- Execution tree: `f8baba05fa84ab717459065685049c4106cdc9f3`
- Draft PR: https://github.com/nieying-code/phrase3/pull/41
- Results evidence commit: `81f776920eb3c4222de110f0b90e0a5feb5c9a2e`
- Results evidence CI: [run 31473988742](https://github.com/nieying-code/phrase3/actions/runs/31473988742), Linux/Windows success

运行开始时工作树无已跟踪修改、无未跟踪执行输入，M1 受控输出目录不存在，且没有残留 Python 或 Gurobi 实验进程。

## 冻结矩阵与执行命令

矩阵严格使用：V1、三个开发种子 `2026081101/02/03`、三档 `beta=0.9/1.1/1.3`、七档 `kappa=unbounded/1.5/1.3/1.2/1.1/1.0/0.8`，形成 `3 × 3 × 7 = 63` 个唯一 primary run。无上限采用 `enabled=false, kappa=null`，没有使用 `Infinity`。

实际命令：

```powershell
.venv-gurobi\Scripts\python.exe -m src.run_phase6_m1_development --config configs/phase6_m1_procurement_cap.yaml --runner-config configs/phase6_m1_runner.yaml --approval configs/phase6_m1_development_approval.yaml --run-id-prefix m1dev_v1_20260811 --authorize-development-execution
```

runner 严格串行运行。每个配置依次完成最低可行储备、完整扩展式最优目标、完整扩展式容差最优面两端、端点逐场景精确补救，以及四个固定自主储备策略；一个配置完全最终化后才进入下一个配置。

## 执行环境和指纹

- Python: `3.12.10`
- Gurobi Optimizer / gurobipy: `13.0.2 / 13.0.2`
- Pyomo interface: `gurobi_direct`
- Threads: `1`
- Scientific: `6439d8a1945e44985cb1c8b20a20b7641617ed9a160db554680f3dc4680aa8c8`
- E3 component: `994e72479f0994c134d112bef1af78421ee3cca25593ab6a9d1146e153afbde2`
- Family component: `05065fba9dd69665bf556da2e6b44fde7e0f73d476172811aeb4d662b74a839d`
- Runner config: `4e39efe184877da9892e63852298bad4f9662b6d09af7ef5fedd6c4a09a13f3a`
- Environment: `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`

## 结果与机器门槛

- 63/63 primary runs 最终化，全部为 `optimal`。
- 63 个 case ID 唯一；重复、诊断重试、无效制品均为 0。
- 补救不可行、求解失败、runner 失败、超时和缺失均为 0；最小/最大端点补救失败也均为 0。
- 252/252 个固定自主储备策略求解均已保存且为最优。
- 21/21 个 beta-kappa 组合均为 3/3 种子最优。
- 数值自主激活 run 数：0/63；实质自主激活 run 数：0/63。
- 所有配置均满足 `R_star = R_min_feas` 且 `R_min_opt = R_min_feas`（审计值最大绝对差均为 0）。
- 最大总储备比例为 `0.3846153846153847`，但全部属于预算等式与采购上限产生的机械储备；最大稳健自主储备比例为 `0.0`。
- 容差最优储备区间最大宽度为 `0.00048493897500634375`，没有形成稳健自主储备。
- 采样总墙钟时间约 `407.0582` 秒，单 run 最大约 `6.6419` 秒；最大采样 RSS 为 `104.484375 MiB`。

最终投影：

```text
development_activation_gate_passed=false
formal_extension_authorized=false
stop_reason=no_preregistered_combination_passed
```

## 科学解释与停止边界

本次预注册范围没有任何 beta-kappa 组合达到“3/3 全部最优且至少 2/3 种子实质自主激活”的进入条件。采购能力约束可以产生正的总储备，但这些储备均等于最低可行机械储备；完整扩展式的容差最优面最小储备没有超过机械下界。

因此，按照预注册规则，M1 扩展在此停止。不得继续降低 kappa、调整应急价格或缺货惩罚、人工选择趋势配置，也不得冻结或启动 M1 正式扩展实验。原 M0 结果保持不变；本批次没有运行 M0 E3、任何 pilot 或任何正式实验。

## 制品与审计

大型原始 result、checkpoint、场景和日志保留在 D 盘受控输出根目录，不提交 GitHub。GitHub 只提交：

- `2026-08-11_phase6_m1_development_grid_audit.json`：63 条 run 的身份、储备分解、端点重评、四策略摘要、制品哈希和执行环境；
- `2026-08-11_phase6_m1_development_grid_projection_summary.json`：21 个组合的机器门槛重汇总；
- 专项审计测试：精确锁定执行提交、tree、五类指纹、全局制品哈希、63 个 case、21 个组合和最终停止结论。

PR #41 首轮复审后，机器审计进一步补齐：每条 run 的 `reference_budget` 和 `budget`；`case_id/run_id` 与 seed-beta-kappa 的双向身份验证；最低可行储备与闭式下界的容差核验；由原始字段重算稳健自主储备及两个激活标志；四种固定自主储备金额公式；以及直接从 63 条 run 重新分组得到 21 个 beta-kappa 组合、3/3 完成数、激活数、组合门槛和最终停止原因。该修复只读取现有最终化制品，没有生成场景或调用 Gurobi。

## 验证结果

- 审计专项测试：`2 passed in 0.07s`
- 完整本地回归：`233 passed in 52.80s`
- Phase 5 端到端：`6 passed in 6.59s`
- Windows 复现专项：`16 passed in 7.86s`
- 语法检查：通过
- `git diff --check`：通过
- GitHub Actions：结果证据提交对应 [run 31473988742](https://github.com/nieying-code/phrase3/actions/runs/31473988742)，Linux 普通回归与 Phase 5、Windows 可复现检查全部成功

## ChatGPT 审查清单

1. 63 个 run 是否形成冻结 seed-beta-kappa 的完整笛卡尔积；
2. 每条 run 的 commit、tree、五类指纹及 result/manifest 哈希是否被锁定；
3. 最低可行储备、最优面两端和端点精确补救是否全部成功；
4. 四个固定自主储备策略是否每个配置均独立保存；
5. 21 个组合是否严格使用 3/3 最优和至少 2/3 实质激活门槛；
6. 正总储备是否被正确区分为机械储备，而未误称为自主激活；
7. 失败、重复、无效和诊断计数是否全部闭合；
8. `formal_extension_authorized` 是否始终为 false；
9. 无组合通过后是否严格停止参数追逐；
10. 是否确实未运行 M0 E3、pilot 或正式扩展实验。
