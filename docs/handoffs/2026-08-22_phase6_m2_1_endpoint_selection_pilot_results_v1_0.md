# Phase 6 M2.1端点选择pilot结果交接

本批在PR #66受审tree `cb55b01f5dbab4279b17eb9e5ccfd5fc8b6d23f6`上，以全新前缀`m21pilot_v10_20260822a`严格串行运行3组三元组。Git smart-HTTP在启动时不可用，因此执行提交记录为本地已保存的PR #66最终head `7d73ab17c2e5fb8b2a5b5d3278f281706a491c72`；其tree与远程main合并提交`4bfaae95b2d55fd068825bf49fd7131e30912885`的tree逐项相同。

## 执行闭合

- 3/3 primary run全部`optimal`并最终化；
- 9/9验证候选、18,000/18,000次验证补救评价成功；
- 一次性测试探针6/6策略、12,000/12,000次补救评价成功；
- 无补救不可行、solver failure、超时、无效制品、重复、诊断或最终化失败；
- Gurobi/gurobipy 13.0.2，`gurobi_direct`，`Threads=1`；
- 总墙钟849.143秒，最大单组三元组490.354秒，最大采样RSS 163.379 MiB；
- 正式10组三元组保守投影1.3621小时，低于72小时门槛。

## 科学结果

三个pilot种子的容差最优储备区间分别为：

| triplet | `R_min_opt` | `R_max_opt` | 验证选择 |
|---|---:|---:|---|
| 1 | 0 | 0.016623 | minimum endpoint |
| 2 | 498.477494 | 498.496500 | minimum endpoint |
| 3 | 1144.341168 | 1144.425759 | minimum endpoint |

三组验证均按照预注册的CVaR95优先规则选择最小端点，且未使用测试数据选择。第1组一次性测试探针中，M2控制和M2.1选择均引用同一个最小端点方案，因此两者测试指标严格相同。该pilot只验证执行链、场景身份、候选选择和计算量；不能据此修改已经冻结的正式设计，也不构成正式M2.1效果结论。

## 停止边界

`pilot_compute_gate_passed=true`，但`formal_extension_authorized=false`。本批没有运行正式训练、正式验证、正式测试、算法性能实验或M0 E3。下一步只能建立独立的正式冻结/授权PR，当前结果PR不授权任何后续实验。

大型原始结果保留在D盘受控输出目录；GitHub仅提交紧凑审计、handoff和专项测试。

本地验证：专项审计`4 passed`、普通回归`544 passed`、Phase 5 `6 passed`、Windows复现专项`16 passed`；`compileall`与`git diff --check`通过。最终CI记录在PR正文中。
