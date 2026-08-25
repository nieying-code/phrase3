# Phase 6 M2 算法性能技术 pilot v1.1 结果交接

## 执行结论

PR #82 合并后的冻结 v1.1 pilot 已从空输出根、使用全新 run ID `m2ap_pilot_v1_1_20260825` 严格串行完成。执行 commit 为 `769dafca0fddf13f3d28287a815a6bca0807454b`，tree 为 `6bcb55edc6db5fa979ea903786c84b9e6d92a8ea`。

- `6/6` primary sequence 全部为 `optimal`；
- `12/12` 预算比较完整；
- 扩展式、标准 C&CG 冷启动和 SPW-C&CG 跨预算热启动共 `36/36` 次求解；
- 三种方法最大目标差为 `3.637978807091713e-12`，满足冻结 M2 目标一致性容差；
- 每个方法均保存完整 `50` 场景精确 oracle 证据；
- 36次oracle均从实际有序键提取身份；有序键哈希逐次等于冻结的 `scenario_order_sha256`，同预算三种方法及同sequence两个预算的联合场景身份均一致；
- 缺失、失败、超时、无效、重复、诊断运行和 CRN 不一致均为 `0`。

## 跨预算迁移与计算投影

六条 sequence 的第二预算均从同一 sequence 的第一预算迁移非空精确场景池。机器审计逐run保存并复算第一预算最终状态及哈希、第二预算来源状态、warm初始池、可复用集合交集、迁移场景、精确成本、全局最坏成本和active/worst集合。共迁移 `10` 个精确场景，`10/10` 均在第二预算成为 active 或 worst 场景，证明迁移路径真实生效，而非仅记录来源身份。

按冻结保守规则，以 pilot 中最大 C&CG worker 时间 `4.053564200003166` 秒估算正式 `240` 次执行：

$$
T_{\mathrm{projected}}
=\frac{240\times4.053564200003166}{3600}
=0.2702376133335444\ \mathrm{h}.
$$

最大采样 RSS 为 `115.421875 MiB`。这些 pilot 时间只用于计算量与执行链验收，不用于提前判断正式速度效应，也不得据此修改正式矩阵。

## 停止边界

`pilot_compute_gate_passed=true`，但 `formal_authorized=false`。本批完成后已停止：没有启动正式 `240` 次执行，也没有启动 M0 E3、M2机制、M2 OOS或M2.1追加实验。正式实验必须在本结果 PR 的机器审计与人工复审通过后另行授权。

大型原始结果继续保留在 `outputs/phase6_m2_algorithm_performance_v1_1/`，GitHub 仅提交紧凑审计、handoff 和专项测试。

## 验证

- 结果专项审计：`4 passed`；
- 干净 worktree 普通回归：`712 passed`；
- Phase 5：`6 passed`；
- Windows 可复现性专项：`16 passed`；
- `git diff --check`：通过；
- 最终 CI 链接记录在 PR 正文中。
