# Phase 6 M2 算法性能正式批次首次证据失败交接

## 结论

PR #84 合并后，实验机在同步且干净的 `main` 上通过完整授权预检，并以全新前缀 `m2ap_formal_v1_20260825` 严格串行启动冻结的 20 条 primary／240 次算法执行。前三条 primary 完整最优；第四条 primary 的第一个 cold worker 虽由 Gurobi 和 C&CG 返回 `optimal`，但其 gap 为一个极小负值，触发冻结的非负证据门槛。批次立即写入不可变 `evidence_invalid` 并停止，后续 primary 未启动。

## 数值诊断

失败 worker 的目标、上下界为：

```text
objective   = 38907.64189347718
lower_bound = 38907.641893477194
upper_bound = 38907.64189347718
gap         = -1.4551915228366852e-11
```

即下界仅比上界高 `1.4551915228366852e-11`。该量远小于本配置对应的冻结目标一致性容差 `0.003900764189347718`，与零 gap 附近的浮点舍入一致。它不是数学模型不可行或 Gurobi 求解失败；但当前正式证据协议明确要求 gap 有限且非负，因此该 primary 不能计入正式门槛。

## 批次闭合

- `3/20` primary 完整最优；第4条为 `evidence_invalid`，其余16条未启动；
- `6/40`预算比较完整；
- `36/240`算法执行完整，第37次 worker 求解完成但证据无效，其余203次未启动；
- projection 为 `formal_algorithm_performance_gate_passed=false`；
- 没有自动重试、诊断run、重复primary或残留Python/Gurobi进程；
- M0 E3、M2机制/OOS及M2.1均未追加运行。

## 后续边界

本 PR 只保存和审计失败证据，不修改 runner、目标容差、模型或求解器，不运行诊断或重试。当前输出根与四条 run 必须永久保留，当前 namespace 不得重新用于完整 primary 批次。

后续如修复，应单独复审“gap 在零附近的数值规范化/验收语义”，确保只吸收冻结容差内的浮点舍入，仍拒绝非有限值和具有实质意义的负 gap；随后升级 namespace、输出根和相关指纹并重新授权。未经复审不得继续正式批次。
