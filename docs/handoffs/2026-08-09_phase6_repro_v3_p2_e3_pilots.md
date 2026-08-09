# Phase 6 repro-v3 P2 E3 pilots and compute-gate handoff

## 任务目标

在已批准的 V1、V2、P1 E3 与 family pilot 基线上，使用三个 pilot
种子严格串行运行 P2：每个种子三档预算、冷/热算法各一次，共18次算法
执行。完成后立即停止求解，并重算完整 Phase 6 计算门槛。

## 分支与执行基线

- Branch: `agent/phase6-p2-repro-v3`
- Base and execution commit: `b53eb42c323f36175ad89940aec1fd460e66a171`
- Execution tree: `bc569a17f3e60d08953f8ba6678b9ffe6fcf6cf9`
- Results commit: `a21d349af1e700c5977ba1e35519f9c1af4da2b9`
- Pull request: https://github.com/nieying-code/phrase3/pull/27
- Output root: `outputs/phase6_v21_repro_v3`
- Python `3.12.10`
- Gurobi Optimizer / gurobipy `13.0.2`
- Pyomo `gurobi_direct`, `Threads=1`, no fallback

五类批准指纹保持不变：

- Scientific: `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3`
- E3: `fd0dc3ea77f850615502005e2caf9f3b7c0259d7c11a9efc7e2a30025c404083`
- Family: `92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e`
- Runner: `3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd`
- Environment: `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`

## P2 pilot结果

- 3/3 primary runs optimal
- 9/9 budget pairs optimal
- 18/18 algorithm executions optimal（冷9、热9）
- 最大冷热目标差：`0.0`
- 最大峰值内存：`210.23828125 MB`
- 无失败、无效制品、重复 primary、父运行或诊断重试
- `early_disposal`、`expired_waste`、`total_disposal`字段均存在

## 完整计算门槛

- E3覆盖：12/12（V1、V2、P1、P2各3条）
- Family前序：12/12 runs，30/30工作单元最优
- E1：`0.0309062300 h`
- E2：`0.1318658700 h`
- E3：`8.7814242456 h`
- E4：`0.7623039050 h`
- E5：`0.0461012073 h`
- 总预计墙钟：`9.7526014579 h <= 168 h`
- 最大单族：E3，`8.7814242456 h <= 72 h`
- `compute_gate_passed=true`
- `formal_execution_authorized=true`

最后两项仅说明机器技术门槛已满足，不等于用户已经授权正式实验。本批完成后
没有启动任何正式种子。

## 制品与审计

紧凑审计文件：
[2026-08-09_phase6_repro_v3_p2_e3_pilots_audit.json](./2026-08-09_phase6_repro_v3_p2_e3_pilots_audit.json)

原始大型result、checkpoint、训练场景和日志仅保留在D盘受控输出根目录，未提交
到Git。审计文件记录三个run的四类制品哈希、9组预算结果、五类指纹、完整投影
及正式实验停止边界。

## 验证与停止边界

- 专项审计测试：`1 passed in 0.08s`
- 完整回归：`158 passed in 37.69s`
- `git diff --check`：通过
- 正式 E1–E5：均未启动

## 下一步

本结果应先形成独立 Draft PR，由 ChatGPT 复审并由用户手动合并。即使机器门槛
已经授权，仍须由用户另行明确正式实验的批次与顺序；不得自动启动正式实验。
