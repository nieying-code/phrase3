# Phase 6 M2C2 双物资确认实验交接

## 执行边界

- 执行分支：`results/phase6-m2c2-confirmation-grid`
- 批准基线提交：`0a036571410e86aeb56e0be778c9644405696104`
- 批准 Git tree：`97997bcfab2a7630716b7a8112a72eb93b8bb3ff`
- 受控输出根：`outputs/phase6_m2c2_confirmation_v1_0`
- run ID 前缀：`m2c2_confirm_v1_20260814`
- 执行前工作树无已跟踪修改、无未跟踪执行输入；30 组严格串行。
- Python 3.12.10，Gurobi/gurobipy 13.0.2，`gurobi_direct`，`Threads=1`。
- 本批未运行 diagnostic、pilot、正式扩展实验或 M0 E3。

## 实验闭合

冻结矩阵为 5 个确认种子、2 档预算和 C0/C1/T03 三个中断档位，共 30 组：

```text
5 × 2 × 3 = 30
```

30/30 个 primary run 均为 `optimal`。无补救不可行、求解失败、超时、无效制品、重复 primary、诊断重试或最终化失败。所有 run 使用相同的五类批准指纹与 Git tree。C0/C1/T03 在相同“种子—预算”组内共享需求潜变量、需求、应急价格、应急供应和场景顺序；履约率按档位变化。

## 确认门槛结果

| 预算 | 档位 | 实质激活种子 | 适度储备种子 | 跨物资动态分配门槛 | C0 等价 |
|---:|:---:|---:|---:|---:|---:|
| 1.1 | C0 | 0/5 | 0/5 | 0/5 | 5/5 |
| 1.1 | C1 | 1/5 | 1/5 | 1/5 | — |
| 1.1 | T03 | 3/5 | 3/5 | 3/5 | — |
| 1.3 | C0 | 1/5 | 1/5 | 1/5 | 5/5 |
| 1.3 | C1 | 3/5 | 3/5 | 2/5 | — |
| 1.3 | T03 | 4/5 | 4/5 | 3/5 | — |

按预注册规则：

- `beta=1.1`：通过。C0 无实质激活且完整恢复无中断模型；T03 有 3/5 个种子同时达到实质激活、适度储备和跨物资动态分配门槛。
- `beta=1.3`：不通过。虽然 T03 激活更频繁，但 C0 对照已有 1/5 个种子实质激活，供应中断归因受到基线激活混杂，机器门槛按设计拒绝。
- 最终仅 `beta=1.1` 进入下一阶段候选；禁止据此讨论预算调节效应。

最终状态：

```text
confirmation_gate_passed=true
passing_betas=[1.1]
claim_scope=single_beta_only_budget_effect_claims_forbidden
overall_decision=permit_separate_formal_extension_design_PR_only
formal_extension_authorized=false
```

## 科学解释边界

本结果支持：在双物资、六期、冻结场景生成协议下，T03 灾害相关供应中断可在 `beta=1.1` 稳定产生非机械、非最优解退化造成的适度自主储备，并在至少 3/5 种子中观察到基于最小储备容差最优端点方案的跨物资动态应急资金分配。

本结果不支持：预算效应、所有预算下的一般性结论、正式政策建议，或“所有最优补救方案都具有相同跨物资分配”的强表述。`beta=1.3` 的 C0 基线激活必须如实报告。

## 可复现材料

- 紧凑机器审计：`docs/handoffs/2026-08-14_phase6_m2c2_confirmation_grid_audit.json`
- 审计生成器：`scripts/build_phase6_m2c2_confirmation_audit.py`
- 独立复算测试：`tests/test_phase6_m2c2_confirmation_grid_audit.py`
- 大型原始 result、manifest、checkpoint、heartbeat、registry 和 projection 保留在 D 盘受控输出根，不提交 GitHub；审计文件锁定其制品哈希与映射哈希。

## 停止边界

本批只完成双物资确认。即使确认门槛通过，正式扩展实验仍未获授权。下一步只能另建、复审并冻结 `beta=1.1` 的正式扩展实验设计；不得由本结果 runner 自动启动。

本地回归与最终 CI 信息在结果 PR 完成后以 PR 正文为最终追溯记录，避免提交自引用。
