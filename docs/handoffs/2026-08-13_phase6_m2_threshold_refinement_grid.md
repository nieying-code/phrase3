# Phase 6 M2 阈值细化开发矩阵 Handoff

## 结果

冻结的27组阈值细化配置已严格串行完成：27/27 primary run 均为 `optimal`，无失败、超时、无效制品、重复运行或诊断重试。未运行双物资确认、正式扩展实验或 M0 E3。

## 执行基线

- 执行提交：`516b6eea1af45b9c1df083963f4ce6eace41425c`
- Git tree：`a489cdaba0932897e2f4eba6686e4778c40c43c7`
- 运行分支：`results/phase6-m2-threshold-refinement`
- 前缀：`m2refine_v1_20260813`
- 工作树：无已跟踪修改、无未跟踪执行输入
- Python 3.12.10；Gurobi/gurobipy 13.0.2；`gurobi_direct`；Threads=1

## 科学结论

三个预算的 C1→T03→T04→T05→C2 激活序列均为：

```text
未激活 → 激活 → 激活 → 激活 → 激活
```

因此三个预算的激活区间均位于 C1（损失尺度0.2）与 T03（0.3）之间，且未观察到非单调激活。所有按 seed—beta 分组的潜变量、需求、应急价格和应急供应共同随机数哈希均一致。

适度自主储备门槛仅由两个组合通过：

- `beta=1.1, profile=T03`
- `beta=1.3, profile=T03`

`beta=0.9,T03` 虽达到2/3实质激活，但仅1/3种子落入5%–50%的预注册适度区间，因此不是双物资候选。

机器结论为：

```text
overall_decision=permit_separate_multi_item_design_PR_only
development_activation_gate_passed=true
moderate_activation_gate_passed=true
formal_extension_authorized=false
```

这只允许另建并受审的双物资确认设计 PR；不授权直接运行双物资实验或正式扩展实验。

## 审计

- 紧凑机器审计：`docs/handoffs/2026-08-13_phase6_m2_threshold_refinement_grid_audit.json`
- 投影摘要：`docs/handoffs/2026-08-13_phase6_m2_threshold_refinement_projection_summary.json`
- 原始大型制品仅保留在 D 盘受控输出根目录，不提交 GitHub。
- 本地验证：阈值 runner 与审计专项 `19 passed`；完整回归 `309 passed`；Phase 5 `6 passed`；`compileall` 与 `git diff --check` 通过。
- Draft PR：[PR #48](https://github.com/nieying-code/phrase3/pull/48)。
- 结果证据提交：`5a17ca471685df7dd58669310d123f91f7a4a1b5`。
- 结果证据 CI：[run 31674421152](https://github.com/nieying-code/phrase3/actions/runs/31674421152)，Linux 与 Windows 均成功。
- 后续若存在纯追溯提交，只更新本记录，不改变实验结果、科学指纹或审计值。
