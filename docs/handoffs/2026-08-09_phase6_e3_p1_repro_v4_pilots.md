# Phase 6 P1 E3 Pilot Handoff（repro v4）

## 任务目标

在 PR #30 合并后的 V1/V2 E3 与 family 前序基线上，严格串行完成 P1 E3 pilot：3 个 pilot 种子、3 档预算、冷/热两种算法各一次，共 18 次算法执行。完成后立即停止并评估 P1 pilot 到 P2 pilot 的规模推进门槛。

## 分支和提交

- Branch: `agent/phase6-e3-p1-repro-v4`
- Base / execution commit: `de1593e94b4cd22653255421a21a0c6b792ffdd2`
- Execution tree: `5424daebb2da574034c5b210e9a4e02d64d1c451`
- Results documentation commit: `10d6f4f`
- Draft PR: https://github.com/nieying-code/phrase3/pull/31
- CI: pending

运行开始时执行提交与 `origin/main` 一致；tracked 修改、未跟踪执行输入均为 0，工作树干净。

## 环境与指纹

- Python 3.12.10；Gurobi/gurobipy 13.0.2；`gurobi_direct`；`Threads=1`
- 无 HiGHS 或其他回退
- Scientific config: `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3`
- E3 component: `20e1b80c1b117e8e801755d754f9005a8b386644c193dcb503396e4f3ec2cc5e`
- Family component: `92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e`
- Runner config: `3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd`
- Environment: `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`

受控读写根为 `outputs/phase6_v21_repro_v3/`。本批次只读取其中已批准的 V1/V2 E3 registry/projection 与 family 前序制品，并写入当前 P1 制品及 E3 汇总；未读取根目录之外的历史输出，没有未提交模型、矩阵、runner 配置或依赖锁参与执行。

## P1 结果

- 3/3 primary runs 为 `optimal`
- 9/9 预算配对为 `optimal`
- 18/18 算法执行为 `optimal`（冷 9、热 9）
- 冷热最大目标差：`0.0`
- 最大峰值内存：`119.42578125 MB`
- 三类处置字段完整
- 无失败、无效制品、重复 primary、父运行或诊断重试

## Pilot 规模推进门槛

- 联合完成率：`9/9 = 1.0`，门槛 `≥ 0.80`
- 单算法单预算墙钟上限：`1800 s`
- 冷启动中位时间：`18.9000415000 s`，比例 `0.0105000231`
- 热启动中位时间：`18.6348526999 s`，比例 `0.0103526959`
- 最大算法中位运行比例：`0.0105000231 ≤ 0.75`
- Pilot 评估：`assessment_passed=true`

该评估只支持是否人工授权 P2 pilot。canonical `scale_advancement.json` 仅由正式 P1 runs 生成并约束正式 P2；本批次没有创建该文件，避免错误授权正式实验。

## 投影与停止边界

- E3 投影：`9/12`，缺失恰为 `P2 × 3 pilot seeds`
- Family 前序：12/12 runs、30/30 工作单元最优
- `compute_gate_passed=false`
- `formal_execution_authorized=false`
- P2 和正式种子均未启动

## 修改文件

- `docs/handoffs/2026-08-09_phase6_e3_p1_repro_v4_pilots.md`
- `docs/handoffs/2026-08-09_phase6_e3_p1_repro_v4_pilots_audit.json`
- `tests/test_phase6_e3_p1_repro_v4_audit.py`

只提交紧凑审计、handoff 和审计测试；原始大结果继续保存在 D 盘，不修改科学代码、模型、矩阵、runner 或指纹。

## 验证结果

- 审计专项测试：`1 passed`
- 完整 pytest：`162 passed in 38.28s`
- `python -m compileall -q src tests`：通过
- `git diff --check`：通过
- GitHub Actions：pending

## 下一步建议

ChatGPT 复审本 PR、用户手动合并并明确授权后，方可运行 P2 E3 pilot（3 个种子 × 3 档预算 × 冷/热算法 = 18 次执行）。本 PR 不启动 P2 或正式实验。

## ChatGPT 审查清单

1. 3/9/18 计数及逐种子预算笛卡尔积是否闭合；
2. 冷热目标是否逐预算一致；
3. 9 个原始冷/热耗时是否能独立重算两个中位数；
4. 运行比例分母是否为 1800 秒，阈值是否精确为 0.80/0.75；
5. Pilot 门槛是否通过且未伪造 canonical formal gate；
6. 五类指纹、执行 commit/tree 和制品哈希是否锁定；
7. E3 是否恰为 9/12，family 前序是否仍为 12/12、30/30；
8. 是否未启动 P2 或正式实验。
