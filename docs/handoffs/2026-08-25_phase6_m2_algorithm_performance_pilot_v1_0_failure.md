# Phase 6 M2 算法性能 pilot 首次执行失败交接

## 结论

PR #80 合并后，实验机在同步的 `main` 上通过全部只读预检，并以全新前缀 `m2ap_pilot_v1_20260825` 启动冻结的 6 条序列/36 次求解批次。批次在第一条 C0 primary、第一预算、完整扩展式阶段立即停止；其余 5 条 primary 和 35 次算法求解没有启动。

失败并非数学模型不可行或 Gurobi 求解失败，而是完整扩展式返回后封装 worker 结果时访问了不存在的 `DisruptedProcurementData.total_budget`。冻结数据对象的实际字段是 `budget`。因此，本次已经生成第一组训练场景并调用一次 Gurobi，但科学结果没有最终化，不能计入 pilot 门槛。

## 不可变证据

- 失败 run：`m2ap_pilot_v1_20260825_M2AP2_pilot_seed2026091001_profileC0`；
- outer/worker 状态分别为 `runner_exception` / `worker_exception`；
- 失败阶段：`complete_extensive_model`；
- projection：0/6 primary、0/12预算配对、0/36有效求解，`pilot_compute_gate_passed=false`；
- registry、result、manifest、worker request/result 与 projection 哈希已经锁定；
- 没有同 run ID 重试、诊断运行、重复记录或残留 Python/Gurobi 进程；
- 正式240次实验及所有其他轨道均未启动。

## 后续边界

本 PR 只记录失败，不修改 runner，也不运行测试性诊断或重试。当前输出根和失败 run 必须永久保留，当前 namespace 不能重新作为完整 primary 批次使用。

后续如修复，应建立独立 runner-fix PR，将错误字段访问改为受接口测试保护的 `data.budget`，使用真实 `GeneratedM2Data/DisruptedProcurementData` 包装边界测试覆盖结果封装路径，并升级指纹、namespace 与空输出根。修复 PR 复审合并后还需要独立重新授权；未经复审不得重跑 pilot。

## 审计验证

- 失败审计专项：2 passed；
- 全新 clean worktree 普通回归：702 passed；
- Phase 5：6 passed；
- Windows 复现专项：16 passed；
- `git diff --check`：通过。
