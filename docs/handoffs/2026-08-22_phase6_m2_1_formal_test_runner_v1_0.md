# Phase 6 M2.1 正式测试 runner v1.0 handoff

## 结论

本PR完成正式测试执行器、安全门槛、状态协议和机器审计，但不开放执行授权。正式测试矩阵固定为10个训练—验证—测试三元组、每组三元组六种策略、每种策略2,000个共同样本外场景，共120,000次精确补救评价。

## 证据与身份边界

- 基线：PR #70合并提交`872040057c3e8d4ae7bcceb3ccbbb706a0e31608`，tree `6c83c1d52424326f70ef0208bf467f38bbcea3d1`。
- PR #70冻结文件SHA-256：`59842e3eb1437ff5a16fa8980e79400dab6504ded032db6d30ef5e5f60302f90`。
- PR #69训练—验证审计、registry和projection均在预检时逐字节复核。
- 10个入选方案严格绑定来源run、case、训练场景、储备金额、采购决策、训练目标和方案制品哈希。
- M2控制使用同一来源run的最小端点；M2.1使用PR #70冻结的入选端点；四个固定策略只读取同一最终化训练run中的方案。
- 每个三元组只生成一次测试场景，六种策略共享七类场景身份，但分别执行2,000次精确评价。

## 执行安全

- 完整primary批次不可拆分，必须使用空输出命名空间和显式CLI授权。
- 单次Gurobi调用上限120秒；单策略墙钟上限7,200秒；`gurobi_direct`、Gurobi/gurobipy 13.0.2、`Threads=1`。
- `time_limit`、墙钟超时、补救失败或制品最终化异常均阻止后续策略和run。
- run ID不可覆盖；诊断重试必须使用新run ID、单一case和失败的`parent_run_id`。
- projection独立复算10/60/120,000、逐策略方案身份、CRN、指标有限性和零失败集合。

## 当前停止边界

```text
selected_plan_freeze_authorized=true
formal_test_runner_implemented=true
formal_test_authorized=false
formal_extension_authorized=false
algorithm_performance_authorized=false
scenario_generation_count=0
gurobi_call_count=0
formal_test_runs=0
M0_E3_runs=0
```

因此当前代码即使带CLI执行参数也会在场景生成前拒绝。下一步只能建立独立的正式测试授权PR。

## 验证

- 专项测试：17 passed。
- 普通回归：584 passed。
- Phase 5：6 passed。
- Windows复现：16 passed。
- `git diff --check`：通过。
- CI：记录于PR正文。
