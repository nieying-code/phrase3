# Phase 6 M2.1正式测试重新授权v1.1

## 授权原因

PR #73修复了正式runner对PR #70冻结审计的字段绑定。该修复不改变数学模型、正式矩阵、统计协议或五类实验指纹，但正式测试编排器哈希从`eb46518c…`变为`e361b803…`，因此PR #72授权已按设计失效。

本次以独立批准文件重新绑定PR #73合并提交、修复审计、修复后的runner、既有PR #70方案冻结及五类批准指纹。旧批准文件不删除、不覆盖，也不能授权当前runner。

## 精确授权范围

- 10条完整primary正式测试run；
- 每条6种已冻结策略；
- 每种策略2,000个共同测试场景；
- 合计60个方案、120,000次精确补救评价；
- 严格串行、空输出命名空间、全新run ID；
- 任一失败、超时、无效、重复或最终化异常立即停止。

实际执行必须显式传入：

```text
--approval configs/phase6_m2_1_formal_test_reauthorization_v1_1.yaml
--authorize-formal-test-execution
```

## 停止边界

本PR只重新授权，不运行实验：

```text
formal_test_runs=0
scenario_generation_count=0
gurobi_call_count=0
algorithm_performance_runs=0
M0_E3_runs=0
formal_extension_authorized=false
algorithm_performance_authorized=false
```

正式输出目录`outputs/phase6_m2_1_formal_test_v1_0`仍必须为空。PR复审并手动合并后，还需用户再次明确下达运行指令。
