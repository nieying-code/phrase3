# Phase 6 M2 正式扩展技术 pilot v1.1 handoff

## 结论

获准的技术批次已完整、严格串行完成：15/15 条机制 pilot 与 1/1 条 OOS 吞吐量探针均为 `optimal`。OOS 探针包含 5 种策略和每种 2,000 个独立样本外场景，共 10,000 次精确补救评价；不可行与求解失败均为 0。

机器投影给出：

```text
pilot_compute_gate_passed=true
next_decision=permit_separate_formal_freeze_PR_only
formal_extension_authorized=false
```

因此，本批只支持另建正式冻结 PR；没有启动 50 条正式机制实验、10 万次正式 OOS 评价、算法性能实验或 M0 E3。

## 执行基线

- 分支：`results/phase6-m2-formal-extension-pilot-v1-1`
- 执行提交：`b1df27402fbd33c7e6f3a2eb1555398a6a9727e1`
- 执行 tree：`50f84608878d1fca42a5f9f8b8cc9a483374a7d2`
- Python：3.12.10
- Gurobi Optimizer / gurobipy：13.0.2 / 13.0.2
- Pyomo 接口：`gurobi_direct`
- Threads：1
- 输出根：`outputs/phase6_m2_formal_extension_v1_1/pilot`
- 开始时工作树：无已跟踪修改、无未跟踪执行输入

五类批准指纹及每条运行的 result、manifest、status-summary 哈希均已写入机器审计。大型原始结果继续保留在 D 盘，不提交 GitHub。

## 运行闭合

机制 pilot 覆盖三个新 pilot 种子：

- `beta=1.1`：C0、C1、T03；
- `beta=1.3`：C0、T03；
- `3 × 5 = 15` 条运行，全部最优；
- 同一种子下需求潜变量、需求、应急价格、应急供应和场景顺序的分量哈希一致；
- 所有容差最优端点均完成精确补救重评；
- 最大端点一致性差为 `0.003822300917818211`，相对冻结目标容差的最大原始超出仅 `1.5735617236306565e-11`，低于批准的投影比较数值余量 `1e-8`。

OOS 探针使用：

- 训练种子：`2026081601`；
- 独立测试种子：`2026081701`；
- 核心配置：`beta=1.1 / T03`；
- 测试场景集合 SHA-256：`3ba7c557e3dc330356bb8ce5169782a504d1ccc888851223b4ba32914018643d`；
- 5 种策略均为 `complete_feasible`，各自 2,000/2,000 场景评价最优。

紧凑审计还逐策略保存并交叉核验了来源机制 run 的最终方案制品哈希、常规采购决策哈希、储备金额、训练目标和训练场景集合哈希。五个 OOS worker 的来源身份与 `first_stage_plan_artifacts` 一一对应；来源方案身份映射 SHA-256 为 `a2288e2861fade5fa6f13ab13197a77b43d4cd9be2d302b41e51db910d058d20`。

## 吞吐量投影

投影使用保守的完成 pilot 最大耗时：

- 单条正式机制运行：`34.009131599988905 s`；
- 单个正式 OOS 方案：`61.710856300007435 s`；
- 50 条机制正式运行预计：`0.4723490499998459 h`；
- 50 个 OOS 正式方案预计：`0.8570952263889922 h`；
- 合计：`1.329444276388838 h`。

16 条运行累计墙钟时间为 `682.1342516000004 s`，观测最大采样 RSS 为 `163.64453125 MiB`。

## 探针的描述性数值

该单一 pilot 种子只用于工程与字段验收，不能作为正式统计结论。内生策略的样本外均值成本为 `15641.5581`、服务水平为 `0.7691`；固定 50% 自主储备的均值成本最低（`10682.0988`）且服务水平最高（`0.8474`），但其 CVaR95 高于内生策略。正式比较仍必须使用冻结的 10 组独立训练—测试种子和预注册统计程序。

## 审计与停止边界

- 机器审计：`docs/handoffs/2026-08-14_phase6_m2_formal_extension_pilot_v1_1_audit.json`
- 专项测试：`tests/test_phase6_m2_formal_extension_pilot_v1_1_results_audit.py`
- registry SHA-256：`4088a8782ad5990f5398407a01191a0cd30489b702d927a57e1df61048709b95`
- projection SHA-256：`111657c0b7a22a50cfd44eee677b0a1a2c0f6adb7299ce19b4f3b2258d4ba6ef`

本 handoff 提交后的最终 PR head 与最终 CI 记录在 PR 正文，避免文档自引用。创建 Draft PR 后停止；未经复审、合并与用户再次明确授权，不运行任何正式实验。
