# Phase 6 V2 E3 Pilot Handoff（repro v4）

## 任务目标

在 PR #29 合并后的冻结执行基线上，严格串行完成 V2 E3 pilot。范围为 3 个 pilot 种子、3 档预算、冷/热两种算法和每种算法 3 次技术重复，共 54 次算法执行。本批次完成后停止，不运行 P1、P2 或正式种子。

## 分支和提交

- Branch: `agent/phase6-e3-v2-repro-v4`
- Base / execution commit: `e7fae479092cbaab35f4ac05fae3001b6b1b94a4`
- Execution tree: `5bb7715fb80a78783488a0f6b33eb00849c2902d`
- Results documentation commit: `af0c49a`
- Draft PR: https://github.com/nieying-code/phrase3/pull/30
- CI: pending

执行提交与当时 `origin/main` 完全一致；tracked 修改数、未跟踪执行输入数均为 0，工作树干净。

## 执行环境

- Python 3.12.10：项目内 `.venv-gurobi`
- Gurobi Optimizer / gurobipy 13.0.2
- Pyomo solver interface: `gurobi_direct`
- Threads: 1
- 无 HiGHS 或其他求解器回退
- 输出根：`outputs/phase6_v21_repro_v3`

## 执行范围与结果

运行 ID：

- `pilot_e3_repro_v4_v2_2026072001`
- `pilot_e3_repro_v4_v2_2026072002`
- `pilot_e3_repro_v4_v2_2026072003`

实际结果：

- 3/3 primary runs 为 `optimal`；
- 9/9 预算配对为 `optimal`；
- 18 个“算法—种子—预算”技术重复组均完成 3 次重复；
- 54/54 次算法执行为 `optimal`；
- 组内三次重复目标最大离差为 0；
- 冷/热目标最大绝对差为 0；
- 6 次相邻预算状态传递完成；
- `early_disposal`、`expired_waste`、`total_disposal` 字段完整；
- 无失败、无制品无效、无重复 primary、无诊断父运行。

三次技术重复仅用于计算时间中位数，不作为独立统计样本。

## 指纹与投影

- Scientific config: `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3`
- E3 component: `20e1b80c1b117e8e801755d754f9005a8b386644c193dcb503396e4f3ec2cc5e`
- Family component: `92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e`
- Runner config: `3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd`
- Environment: `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`

E3 当前覆盖从 3/12 更新为 6/12：V1 3 条和 V2 3 条有效；缺失恰为 P1/P2 各 3 条。`compute_gate_passed=false`、`formal_execution_authorized=false` 均符合当前阶段。

## 修改文件

- `docs/handoffs/2026-08-09_phase6_e3_v2_repro_v4_pilots.md`：结果 handoff。
- `docs/handoffs/2026-08-09_phase6_e3_v2_repro_v4_pilots_audit.json`：紧凑机器审计快照。
- `tests/test_phase6_e3_v2_repro_v4_audit.py`：审计闭环测试。

未提交原始结果、场景、checkpoint 或大型日志；没有修改模型、算法、矩阵、runner 或科学指纹。

## 验证结果

- V2 三条 run：3/3 `optimal`
- 预算配对：9/9 `optimal`
- 算法执行：54/54 `optimal`
- 最大重复内目标离差：0
- 最大冷热目标差：0
- E3 投影：6/12
- 机器审计专项测试：`1 passed`
- 完整 pytest：`161 passed in 37.86s`
- `python -m compileall -q src tests`：通过
- `git diff --check`：通过
- GitHub Actions：pending

## 已知限制与停止边界

本批次只验证 V2 pilot。P1、P2 和正式种子均未启动；当前结果不能被解释为正式实验结果或正式执行授权。

## 下一步建议

由 ChatGPT 通过 Draft PR 复审 V2 的 3/9/54 闭环、重复定义、目标一致性、制品哈希和 6/12 投影。用户手动合并后，再另行明确授权 P1 E3 pilot；不得由本 PR 自动进入 P1。

## ChatGPT 审查清单

1. 三个 run 是否均为 V2、pilot、无父运行且指纹一致；
2. 3 个种子是否分别具有 0.9/1.1/1.3 三档预算；
3. 每个预算和算法是否恰有 3 次技术重复；
4. 54 次执行是否全部最优，组内目标是否一致；
5. 冷热目标是否逐预算一致；
6. 6 次相邻预算状态传递是否成立；
7. 三类库存处置字段是否存在；
8. 全局 registry/projection 哈希是否锁定；
9. E3 是否恰为 6/12，异常列表是否为空；
10. 是否严格停止在 V2、未启动 P1/P2/formal。
