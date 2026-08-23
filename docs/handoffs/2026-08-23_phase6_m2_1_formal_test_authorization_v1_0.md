# Phase 6 M2.1 正式测试授权 v1.0 handoff

## 结论

本PR只新增独立正式测试授权制品，不修改PR #71受审runner、模型、矩阵、统计协议或历史未授权批准文件。授权范围严格限于一次完整的10条M2.1正式测试primary批次。

## 绑定证据

- PR #71合并提交：`2d60923cadaeb6c92401429cf3907c174170b3d8`。
- PR #71合并tree：`d91129f28e1f14296e629e710e49c5f52ca215f0`。
- Runner审计SHA-256：`2832421394d5e44a79781e36f5242047ff657f243501418e04616e10bfc9b3ad`。
- 正式测试编排器SHA-256：`eb46518ce1c090a1da798a49fb27ae006ffdf42b89886f1292b3bee8bd33b07a`。
- PR #70冻结文件SHA-256：`59842e3eb1437ff5a16fa8980e79400dab6504ded032db6d30ef5e5f60302f90`。

授权测试机械核对上述审计、runner、CLI、状态工具和runner配置字节，防止授权文件与另一执行器组合使用。

## 运行边界

授权合并后仍必须由用户单独明确下令，并显式使用：

```text
--approval configs/phase6_m2_1_formal_test_authorization_v1_0.yaml
--authorize-formal-test-execution
```

完整primary运行必须从空的`outputs/phase6_m2_1_formal_test_v1_0`命名空间开始，使用全新run ID前缀，严格串行完成10条run、60个方案和120,000次精确补救评价。任何失败、超时、制品无效或重复primary立即停止。

```text
formal_test_authorized=true
formal_extension_authorized=false
algorithm_performance_authorized=false
scenario_generation_count=0
gurobi_call_count=0
formal_test_runs=0
M0_E3_runs=0
```

本PR不运行实验。即使正式测试结果门槛通过，也只能提交结果Draft PR复审，不能自动启动算法性能实验。

## 验证

- 授权专项测试：6 passed。
- 普通回归：593 passed。
- Phase 5：6 passed。
- Windows复现：16 passed。
- `git diff --check`：通过。
- CI：记录于PR正文。
