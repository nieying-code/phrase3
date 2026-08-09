# Phase 6 Formal Projection Guard Handoff

## 任务目标

修复正式 E3 序列完成后错误重建 pilot 投影、从而撤销正式授权并阻断下一条正式 E3 run 的问题。本任务只修改执行控制与回归测试，不运行 pilot、正式种子、场景生成或 Gurobi 实验。

## 分支和提交

- Branch: `agent/fix-phase6-formal-projection`
- Base branch: `main`
- Base commit: `d7a67d59ab4b7abfa4c25fa0e05dd6c6e2961540`
- Implementation commit: `04f775fe59b6b81790b11f375ce5601d78be0422`
- Final PR head: see Draft PR after the handoff-link commit
- PR: https://github.com/nieying-code/phrase3/pull/28
- CI: GitHub Actions run `31303233553`, success（覆盖实现提交与首次 handoff 链接提交）

## 根因

`run_phase6_sequence()` 在每次 E3 run 最终化后无条件调用 `update_pilot_projection()`。该函数只重建 E3 pilot 覆盖，并把 E1、E2、E4、E5 投影初始化为 unavailable，因此会把已有的完整计算门槛重写为：

```text
compute_gate_passed=false
formal_execution_authorized=false
```

第一条正式 E3 能通过启动前门槛，但完成后会撤销授权，使第二条正式 E3 在场景生成前被拒绝。现有测试只覆盖单次正式运行的启动前检查，没有覆盖连续正式运行。

## 修改内容

- 正式 E3 启动时保存已通过验证的投影快照。
- 正式 E3 最终化时沿用该只读快照，不调用、也不覆盖 pilot projection。
- pilot 和开发模式继续按原逻辑重建 pilot projection。
- 增加两条连续正式 E3 run 的回归测试，验证：
  - 每条 run 都重新执行启动前授权检查；
  - formal 模式绝不调用 `update_pilot_projection()`；
  - 两条 run 均保持 `formal_execution_authorized=true`。

## 修改文件

- `src/phase6_runner.py`：区分 formal 与非 formal 的投影最终化路径。
- `tests/test_phase6_runner.py`：增加连续 formal E3 回归测试。
- `docs/handoffs/2026-08-01_phase6_reproducibility_hardening_audit.json`：将当前执行基线更新到新的 E3 组件指纹，并保留旧 pilot 审计文件不变。
- `docs/handoffs/2026-08-09_phase6_formal_projection_guard.md`：本交接记录。

## 指纹影响

- 科学配置：保持 `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3`。
- E3 旧组件指纹：`fd0dc3ea77f850615502005e2caf9f3b7c0259d7c11a9efc7e2a30025c404083`。
- E3 当前组件指纹：`20e1b80c1b117e8e801755d754f9005a8b386644c193dcb503396e4f3ec2cc5e`。
- family 组件指纹：保持 `92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e`。
- E3 runner 配置指纹：保持 `3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd`。
- 环境指纹：保持 `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`。

由于 `phase6_runner.py` 属于 E3 受保护组件，旧 V1/V2/P1/P2 E3 pilot 不得进入新门槛，需在本 PR 合并后使用全新 run ID 重新建立 12/12 E3 pilot。family 指纹未变化，已批准的 12/12 family runs、30/30 工作单元可以保留，但需在新 E3 投影建立后重新机械汇总完整门槛。

## 验证结果

- `python -m pytest tests/test_phase6_runner.py tests/test_phase6_reporting.py -q`
  - `24 passed in 11.54s`
- `python -m compileall -q src tests`
  - 通过
- `git diff --check`
  - 通过
- `python -m pytest -q`
  - `159 passed in 38.00s`
- GitHub Actions run `31303233553`
  - Linux 常规回归与 Phase 5 端到端：通过
  - Windows 复现守卫：通过

## 实验停止边界

本分支没有运行或授权以下任务：

- 新 V1/V2/P1/P2 pilot；
- family pilot 重跑；
- E1–E5 正式实验；
- 任何正式种子；
- P1 → P2 正式规模推进。

## 风险与审查重点

1. formal 模式是否仍在每次 run 开始前验证完整投影。
2. formal run 最终化是否不再写入 `pilot_throughput_projection.json`。
3. pilot 模式是否仍能正常刷新覆盖率和吞吐率。
4. 失败、manifest、registry、性能表和状态摘要的最终化顺序是否保持不变。
5. E3 指纹是否按设计改变，family 指纹是否保持不变。

## 下一步建议

PR 通过复审并由用户手动合并后，从最新 `main` 建立干净运行分支，按 V1 → family 投影重汇总 → V2 → P1 → P1 门槛 → P2 的受审批次顺序重新建立 E3 pilot 门槛。完成 12/12 与完整计算门槛复审之前，不启动正式实验。
