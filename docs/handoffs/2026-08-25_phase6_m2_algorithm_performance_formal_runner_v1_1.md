# Phase 6 M2 算法性能正式批次 gap 修复与重新授权

## 范围

本 PR 基于 PR #85 合并提交 `aadbf01de69804f493f80ccbb1b4cd06d5b0cbb6`，只修复零 gap 附近的数值证据规范化，并在新命名空间中重新授权原封不动的 `20/40/240` 正式矩阵。本 PR 不生成场景、不调用 Gurobi、不运行科学实验。

- 受审 runner 提交：`1e855af3936cc19c6a6ab75a7b59efcf357a85b2`
- 受审 runner tree：`ec3f82e8a33c2065259e0c415812f1dac13f4eb7`
- 新命名空间：`phase6_m2_algorithm_performance_formal_v1_1`
- 新输出根：`outputs/phase6_m2_algorithm_performance_formal_v1_1`

## gap证据规范化

仅对机器验收层应用既有绝对数值保护量 `1e-9`：

- `gap < -1e-9`：拒绝；
- `-1e-9 <= gap < 0`：保留原始 `reported_optimality_gap`，机器验收字段规范化为 `0.0`；
- `gap >= 0`：保持原值；
- `NaN`、正负无穷：拒绝；
- reported gap 必须与 `upper_bound-lower_bound` 在 `1e-9` 内一致。

科学目标一致性容差不参与 gap 规范化。本 PR 未修改数学模型、C&CG 收敛条件、目标容差、求解器、矩阵或统计协议。

## 隔离与授权

旧 `v1_0` 输出、三条最优 primary 和一条 `evidence_invalid` primary 永久保留，只作为历史执行证据，不迁移到新 registry/projection。合并后只能从空的 `v1_1` 输出根、使用全新 run ID，从头执行完整 `20/40/240` 批次。M0 E3、M2机制/OOS和M2.1追加运行继续关闭。

## 非执行声明

- `scenario_generation_count=0`
- `gurobi_call_count=0`
- `algorithm_performance_runs=0`
