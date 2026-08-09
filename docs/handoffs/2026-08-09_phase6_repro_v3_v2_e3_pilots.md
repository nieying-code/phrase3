# Phase 6 repro-v3 V2 E3 pilot handoff

## 任务目标

在 PR #24 合并后的已批准 V1 E3 与 family pilot 基线上，严格串行完成 V2 E3 pilot：3 个 pilot 种子、3 个预算、冷/热两种算法、每种算法 3 次技术重复，共 54 次算法执行。V2 完成后立即停止，不进入 P1。

## 分支和提交

- Branch: `agent/phase6-v2-repro-v3`
- Base: merged `main` commit `b9371d4ba36bd8b578cb366aaa4f56b9d839b472`
- Results commit: `52da67a013c596eea76d57c7278f0fbfec9e4a75`
- Pull request: https://github.com/nieying-code/phrase3/pull/25
- CI: pending

## 执行环境与基线

- 受控输出根目录：`outputs/phase6_v21_repro_v3`
- Python `3.12.10`
- Gurobi Optimizer / gurobipy `13.0.2`
- Pyomo `gurobi_direct`
- `Threads=1`
- 无 HiGHS 或其他求解器回退
- 执行开始时 tracked 修改数为 0、untracked 路径为空，三个 manifest 均记录干净工作树。

指纹保持不变：

- Scientific configuration: `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3`
- E3 component: `fd0dc3ea77f850615502005e2caf9f3b7c0259d7c11a9efc7e2a30025c404083`
- Family component: `92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e`
- Runner config: `3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd`
- Environment: `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`

## 结果

- Primary runs：3/3 `optimal`
- 预算配对：9/9 `optimal`
- 算法执行：54/54 `optimal`
- 技术重复组：18 组；三次重复只用于计时中位数，不作为独立统计样本
- 冷启动：27 次；热启动：27 次
- 技术重复内最大目标差：`0.0`
- 冷热最大目标差：`0.0`
- 冷启动中位执行时间：`2.1600070001 s`
- 热启动中位执行时间：`2.1408124999 s`
- 最大峰值内存：`77.8828125 MB`
- 6 次相邻预算传递均复用了已转移场景；平均热池复用比例为 `2/9`
- `early_disposal`、`expired_waste`、`total_disposal` 字段均存在
- 无失败、无效制品、重复 primary、父运行或诊断重试

详细逐 run 哈希、9 个预算配对、计时、迭代和场景复用字段见 [机器审计 JSON](./2026-08-09_phase6_repro_v3_v2_e3_pilots_audit.json)。大型原始结果、checkpoint、场景和日志只保留在 D 盘受控输出根目录，不提交 GitHub。

## 投影与停止边界

- E3 投影由 `3/12` 更新为 `6/12`：V1 3 条 + V2 3 条。
- Family 前序保持 12/12 runs、30/30 工作单元最优。
- 投影状态：`insufficient_pilot_coverage`。
- `compute_gate_passed=false`。
- `formal_execution_authorized=false`。
- P1、P2 和正式种子均未启动。

本批次已经停止。未经 ChatGPT 复审和用户手动合并，不运行 P1。

## 验证

- 审计专项测试：`.venv-gurobi\\Scripts\\python.exe -m pytest tests\\test_phase6_repro_v3_v2_pilot_audit.py -q` → `1 passed in 0.07s`
- 完整回归：`.venv-gurobi\\Scripts\\python.exe -m pytest -q` → `156 passed in 48.24s`
- `git diff --check`：通过
- GitHub Actions：pending

## 修改文件

- `docs/handoffs/2026-08-09_phase6_repro_v3_v2_e3_pilots.md`
- `docs/handoffs/2026-08-09_phase6_repro_v3_v2_e3_pilots_audit.json`
- `tests/test_phase6_repro_v3_v2_pilot_audit.py`

本 PR 仅提交紧凑审计、handoff 与审计测试，不修改模型、算法、矩阵、runner、配置或指纹。

## 下一步建议

PR 复审并由用户手动合并后，下一批只能运行 P1 E3 pilot：3 个 pilot 种子 × 3 个预算 × 2 种算法 × 1 次重复，共 18 次算法执行。P1 完成后立即停止并计算规模推进门槛，不自动进入 P2。

## ChatGPT 审查清单

1. `3 × 3 × 2 × 3 = 54` 计数是否闭合；
2. 18 个技术重复组是否仅以种子为统计独立单位；
3. 所有重复及冷热目标是否一致；
4. 计时、迭代、场景复用和峰值内存是否完整；
5. 三类处置字段是否存在；
6. 三类指纹、runner 与环境指纹是否匹配批准基线；
7. E3 是否准确更新为 6/12；
8. Family 12/12 与 30/30 前序是否保持有效；
9. 是否没有失败、无效制品、重复 primary 或诊断重试；
10. 是否未启动 P1、P2 或正式实验。
