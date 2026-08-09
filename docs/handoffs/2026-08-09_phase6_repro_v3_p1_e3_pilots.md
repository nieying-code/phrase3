# Phase 6 repro-v3 P1 E3 pilot handoff

## 任务目标

在 PR #25 合并后的 V1、V2 E3 与 family pilot 基线上，严格串行完成 P1 E3 pilot：3 个种子、3 档预算、冷/热两种算法各一次，共 18 次算法执行。完成后立即停止并评估 P1 pilot 到 P2 pilot 的规模推进门槛。

## 分支和提交

- Branch: `agent/phase6-p1-repro-v3`
- Base: merged `main` commit `1440b288cc875d0ff70b2acbd581ae75764a7724`
- Results commit: `159a7eb34ad209a4278b0faf60ec1b70a87ce108`
- Pull request: https://github.com/nieying-code/phrase3/pull/26
- PR validation head before final tracking-only update: `b18f36851ae883f256ff0e34b790ae2cfe831625`
- CI: GitHub Actions run `31297846266` succeeded for the validation head; the final tracking-only head is reported in the PR description after its CI reaches a terminal state.

## 环境与执行基线

- 输出根目录：`outputs/phase6_v21_repro_v3`
- Python `3.12.10`
- Gurobi Optimizer / gurobipy `13.0.2`
- Pyomo `gurobi_direct`
- `Threads=1`
- 无 HiGHS 或其他求解器回退
- 三条 run 开始时 tracked 修改数为 0、untracked 路径为空，manifest 均记录干净工作树。

批准指纹保持不变：

- Scientific configuration: `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3`
- E3 component: `fd0dc3ea77f850615502005e2caf9f3b7c0259d7c11a9efc7e2a30025c404083`
- Family component: `92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e`
- Runner config: `3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd`
- Environment: `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`

### Controlled output provenance clarification

`outputs/phase6_v21_repro_v3/` was the controlled read/write root. The P1
runner read the already approved V1/V2 E3 registry and projection plus the
approved family prerequisite registry and finalized family result manifests
inside that same root. It wrote only the current P1 E3 run artifacts and the
corresponding E3 registry/projection updates. No historical output directory
outside this controlled root was used as input, and no uncommitted model,
scientific configuration, matrix, runner configuration, or dependency lock
participated in execution.

## P1 结果

- Primary runs：3/3 `optimal`
- 预算配对：9/9 `optimal`
- 算法执行：18/18 `optimal`（冷 9、热 9）
- 冷热最大目标差：`0.0`
- 冷启动中位时间：`18.7495066000 s`
- 热启动中位时间：`18.9278362000 s`
- 最大峰值内存：`125.82421875 MB`
- `early_disposal`、`expired_waste`、`total_disposal` 均存在
- 无失败、无效制品、重复 primary、父运行或诊断重试

## Pilot 规模推进门槛

- 计划配对：9；冷热联合最优配对：9
- 联合完成率：`1.0`，门槛为 `≥ 0.80`
- P1 单算法单预算墙钟上限：`1800 s`
- 冷启动中位运行时间比例：`0.0104163926`
- 热启动中位运行时间比例：`0.0105154646`
- 最大比例：`0.0105154646`，门槛为 `≤ 0.75`
- Pilot 评估：`assessment_passed=true`

该结论只支持“是否授权 P2 pilot”的人工复审。代码中的 canonical `scale_advancement.json` 只由正式 P1 runs 生成并约束正式 P2；本批次没有创建该文件，避免错误授权正式实验。

## 投影与停止边界

- E3 投影：`9/12`（V1、V2、P1 各 3 条）。
- Family 前序：12/12 runs、30/30 工作单元最优。
- `compute_gate_passed=false`。
- `formal_execution_authorized=false`。
- P2 和正式种子均未启动。

完整逐 run 哈希、9 个预算配对及门槛计算见 [机器审计 JSON](./2026-08-09_phase6_repro_v3_p1_e3_pilots_audit.json)。大型结果、checkpoint、场景与日志只保留在 D 盘受控输出根目录。

## 验证

- 审计专项测试：`.venv-gurobi\\Scripts\\python.exe -m pytest tests\\test_phase6_repro_v3_p1_pilot_audit.py -q` → `1 passed in 0.04s`
- 完整回归：`.venv-gurobi\\Scripts\\python.exe -m pytest -q` → `157 passed in 38.84s`
- `git diff --check`：通过
- GitHub Actions：run `31297846266`，Linux tests 与 Windows reproducibility check 均成功

## 修改文件

- `docs/handoffs/2026-08-09_phase6_repro_v3_p1_e3_pilots.md`
- `docs/handoffs/2026-08-09_phase6_repro_v3_p1_e3_pilots_audit.json`
- `tests/test_phase6_repro_v3_p1_pilot_audit.py`

本 PR 只提交紧凑审计、handoff 与审计测试，不修改模型、算法、矩阵、runner、配置或指纹。

## 下一步建议

只有 ChatGPT 复审本 PR、用户手动合并并明确授权后，才能运行 P2 E3 pilot：3 个种子 × 3 档预算 × 冷/热两种算法，共 18 次算法执行。P2 完成后立即停止并执行完整计算门槛复审，不自动启动正式实验。

## ChatGPT 审查清单

1. 3/9/18 计数与逐种子预算笛卡尔积是否闭合；
2. 冷热目标是否逐预算一致；
3. 运行时间比例分母是否为 P1 单算法单预算墙钟上限 1800 秒；
4. 联合完成率和最大中位运行比例是否满足冻结门槛；
5. 是否没有伪造 canonical formal gate；
6. 五类指纹及执行 commit/tree 是否精确匹配批准基线；
7. E3 是否为 9/12，family 前序是否仍有效；
8. 是否未启动 P2 或正式实验。
