# Phase 6 P2 E3 Pilot Handoff（repro v4）

## 任务目标

在 PR #31 合并后的 V1/V2/P1 E3 与 family 前序基线上，严格串行完成 P2 E3 pilot：3 个 pilot 种子、3 档预算、冷/热算法各一次，共 18 次执行。完成后立即停止，不执行最终 family 投影重汇总或正式实验。

## 分支和提交

- Branch: `agent/phase6-e3-p2-repro-v4`
- Base / execution commit: `921b9e0866ce7d3856ff2275d4159f9702b5b942`
- Execution tree: `42b480ec855e8eb90bb33c09de47adcc33f63300`
- Results documentation commit: pending
- Draft PR: pending
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

受控读写根为 `outputs/phase6_v21_repro_v3/`。本批次读取已批准的 V1/V2/P1 E3 汇总、family 前序和 P1 pilot 门槛审计，只写入 P2 制品与 E3 汇总；未读取外部历史输出，没有未提交执行输入。

## P2 结果

- 3/3 primary runs 为 `optimal`
- 9/9 预算配对为 `optimal`
- 18/18 算法执行为 `optimal`（冷 9、热 9）
- 冷热最大目标差：`0.0`
- 最大峰值内存：`207.265625 MB`
- 三类处置字段完整
- 无失败、无效制品、重复 primary、父运行或诊断重试

第三条 run 的外层 shell 观察上限为 900 秒并返回 124；检查时该科学 run 已完整最终化为 `optimal`，result、manifest、registry 和哈希均存在，无 runner exception 或残留 Python 进程。本批次没有使用相同 run ID 重试。机器审计显式记录此事件。

## 投影与停止边界

- E3 pilot 覆盖：`12/12`，V1/V2/P1/P2 各 3 条
- E3 工时投影：`8.8692564867 h`
- Family 前序制品仍为 12/12 runs、30/30 工作单元最优
- 当前总投影状态：`projection_incomplete`
- `compute_gate_passed=false`
- `formal_execution_authorized=false`
- 最终 family 投影重汇总尚未执行
- 正式种子未启动

这是预期停止状态。P2 结果复审并合并后，下一批任务应只读取现有 family 制品进行最终投影重汇总和完整计算门槛复审，不直接启动正式实验。

## 修改文件

- `docs/handoffs/2026-08-09_phase6_e3_p2_repro_v4_pilots.md`
- `docs/handoffs/2026-08-09_phase6_e3_p2_repro_v4_pilots_audit.json`
- `tests/test_phase6_e3_p2_repro_v4_audit.py`

只提交紧凑审计、handoff 和审计测试；原始大型结果保存在 D 盘，不修改科学代码、模型、矩阵、runner 或指纹。

## 验证结果

- 审计专项测试：`python -m pytest tests/test_phase6_e3_p2_repro_v4_audit.py -q`，`1 passed in 0.08s`
- 完整 pytest：`python -m pytest -q`，`163 passed in 40.86s`
- 语法检查：`python -m compileall -q src tests`，通过
- `git diff --check`：通过
- GitHub Actions：pending

## 下一步建议

ChatGPT 复审本 PR、用户手动合并并明确授权后，仅执行最终 family 投影重汇总和完整计算门槛审查。即使机器门槛随后通过，也必须等待用户另行批准正式实验批次。

## ChatGPT 审查清单

1. 3/9/18 计数及逐种子三档预算是否闭合；
2. 冷热目标是否逐预算一致；
3. 五类指纹、执行 commit/tree 和每条制品哈希是否锁定；
4. 第三条 run 的 shell 观察超时与已最终化科学结果是否被准确区分；
5. E3 是否恰为 12/12 且异常列表为空；
6. Family 前序是否仍为 12/12、30/30；
7. 当前 `projection_incomplete` 是否源于尚未最终重汇总 family 投影；
8. 是否未启动正式实验。
