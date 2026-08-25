# Phase 6 M2 算法性能 runner 与 pilot 冻结交接

## 结论

本 PR 在 PR #78 合并后的冻结设计上实现独立的 M2 算法性能执行器，但不授权、也不运行 pilot 或正式实验。下一步仍需独立授权 PR 才能运行 6 条 pilot 序列（36 次求解）。

## 冻结工作量

- Pilot：3 个新种子 × 2 个档位（C0/T03）× 2 个预算 × 3 种方法（完整扩展式、标准 C&CG、SPW-C&CG）= 36 次求解。
- 正式矩阵：10 个新种子 × 2 个档位 × 2 个预算 × 2 种算法 × 3 次技术重复 = 240 次执行；本 PR 未实现正式启动入口。
- `beta=1.1` 只建立首个场景池；`beta=1.3` 才是跨预算迁移证据。

## 执行安全

- 独立 namespace、输出根、registry、projection、CLI 和状态工具。
- 首次场景生成前复算双物资参考预算、两档实际预算和六期容量。
- 每次算法求解在新子进程中执行；Gurobi 单次限制 120 秒，外层 worker 限制 180 秒，单线程。
- Pilot 严格按 `seed → profile → beta` 串行；预算 0 为 EF→cold→warm，预算 1 为 EF→warm→cold。
- 第二预算 warm 只读取第一预算 warm 的精确场景池；完整精确 oracle 始终保留。
- 原生 `time_limit`、`master_time_limit` 与外层墙钟超时均形成不可变 timeout，并停止后续方法和 case。
- 任一目标不一致、CRN 不一致、制品无效、失败、重复或诊断记录都会阻断 pilot 门槛。
- Worker 显式解析并传入冻结的 C0/T03 profile；mock 边界测试不生成场景即可覆盖真实包装路径。
- C&CG 收敛容差与 M2 科学目标一致性容差分离；三方法比较固定使用 `1e-5 + 1e-7 × max(1, |z|)`。
- cold/warm 必须保存50/50精确 oracle、跨预算相同场景身份以及第二预算的第一预算 warm 状态来源、迁移数量和复用率。
- Pilot projection 从明细重算36次求解，并以最大 pilot C&CG 子进程时间保守投影正式240次墙钟与峰值内存。
- 状态工具只读取不超过 16 KiB 的小型状态文件，不解析大型 result/checkpoint。

## 授权边界

当前批准文件状态为 `runner_frozen_pilot_pending_authorization`：

- `pilot_authorized=false`；
- `formal_authorized=false`；
- M0 E3、M2 mechanism、M2 OOS、M2.1 追加运行均为 false；
- CLI 即使带显式参数，也会在场景生成和 Gurobi 前因未授权而拒绝。

## 本 PR 执行计数

- 场景生成：0；
- Gurobi 调用：0；
- pilot primary：0；
- pilot 算法求解：0；
- 正式 primary：0；
- 正式算法执行：0；
- M0/M2/M2.1 追加实验：0。

## 验证

- 新旧专项测试：22 passed。
- 全新 clean worktree 普通回归：694 passed。
- Phase 5：6 passed；Windows 复现专项：16 passed。
- 原实验工作树保留 PR #75/#77 输出且未移动、删除或覆盖；测试使用的 clean worktree 不含这些历史输出。
- Linux/Windows CI 与最终 head 在 PR 中记录。
- `git diff --check`：通过。

完成 Draft PR 后停止；不得运行 pilot、正式 240 次实验或其他科学实验。
