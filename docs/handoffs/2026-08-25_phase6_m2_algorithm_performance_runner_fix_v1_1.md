# Phase 6 M2 算法性能 runner v1.1 修复说明

## 修复范围

本修复针对 PR #81 锁定的首次 pilot 失败，只修改结果封装接口：将不存在的 `DisruptedProcurementData.total_budget` 改为冻结数据类实际提供的 `DisruptedProcurementData.budget`。数学模型、场景生成、三种算法、预算、种子、容差、求解器设置和 6/12/36 pilot 矩阵均未改变。

## 隔离与测试

- 新 runner namespace：`phase6_m2_algorithm_performance_v1_1`；
- 新空输出根：`outputs/phase6_m2_algorithm_performance_v1_1`；
- 旧 v1.0 失败输出永久保留且不作为新门槛输入；
- 新增真实 `GeneratedM2Data` / `DisruptedProcurementData` 包装对象测试，在 mock 求解器返回后走完整 worker 结果封装路径，验证 `budget` 字段能够写出且不存在 `total_budget`；
- 测试不生成正式场景、不调用 Gurobi。

## 审批绑定

- 第一提交（runner 修复）：`03978b0efce768672233079ea23364c6ca632418`，tree `14114651d54c3169b3e87c72907557c2041032b1`；
- 第二提交仅绑定审批、机器审计、handoff 和专项测试，不再修改科学 runner；
- 审批只开放完整 `6` 条 primary、`12` 组预算比较和 `36` 次 pilot 求解；
- 正式 `240` 次算法执行及 M0 E3、M2机制、M2 OOS、M2.1 的任何追加实验均保持关闭；
- 合并本 PR 后仍须从与 `origin/main` 同步的 `main`、使用显式 CLI 授权参数和全新 run ID，从空的 v1.1 输出根完整重跑；旧 v1.0 失败 run 永久保留且不得复用。

本 PR 阶段仅运行测试和真实实验环境只读预检，场景生成数、Gurobi 调用数和科学实验运行数均为 `0`。

## 本地验证

- runner、旧授权兼容和新审批绑定专项：`27 passed`；
- 干净 worktree 普通回归：`708 passed`；
- Phase 5：`6 passed`；
- Windows 可复现性专项：`16 passed`；
- `git diff --check`：通过；
- 实验机只读预检：六类指纹与审批完全一致，Gurobi Optimizer / gurobipy 均为 `13.0.2`；
- 场景生成数：`0`；Gurobi 求解调用数：`0`；pilot、正式及其他科学实验运行数：`0`。

最终 CI 链接记录在 PR 正文中。
