# Phase 6 M2 算法性能 pilot 授权交接（v1.0）

## 授权结论

本 PR 以 PR #79 的合并提交 `72c430e9c12bb3aca9d65f9d69fe257aa71591a0` 为唯一执行器基线，只开放冻结的 M2 算法性能技术 pilot，不修改模型、矩阵、求解器、容差、种子、预算、场景数量或执行顺序。

授权矩阵仍为：3 个 pilot 种子 × 2 个中断档位（C0/T03）× 2 个预算 × 3 种方法，共 6 条 primary 序列、12 组预算比较和 36 次算法求解。所有运行必须严格串行；任一失败、超时、目标不一致、oracle 身份错误、迁移证据错误或制品无效都会停止整批。

## 执行门槛

- approval 必须为 `status=frozen_for_pilot_execution` 且 `pilot_authorized=true`；
- CLI 必须显式提供 `--authorize-m2-algorithm-performance-pilot`；
- 本地分支必须为跟踪 `origin/main` 的 `main`，且 `HEAD` 等于已获取的 `origin/main`；
- PR #79 合并提交必须为执行 `HEAD` 的祖先；
- Python 3.12.10、Gurobi/gurobipy 13.0.2、`gurobi_direct`、`Threads=1` 与六类批准指纹必须全部匹配；
- 输出根必须不存在或为空，并使用全新 run ID 前缀。

## 保持关闭的范围

正式 240 次性能实验尚未实现且未授权；M0 E3、M2 mechanism、M2 OOS 和 M2.1 的任何追加运行也未授权。Pilot 完成后只能生成结果 PR 并停止复审，不能自动进入正式实验。

本授权 PR 不生成场景、不调用 Gurobi、不运行 pilot。最终提交、测试和 CI 记录在 PR 正文中。

## 本地验证

- 设计、runner 与授权专项：28 passed；
- 全新 clean worktree 普通回归：700 passed；
- Phase 5：6 passed；
- Windows 复现专项：16 passed；
- `git diff --check`：通过。
