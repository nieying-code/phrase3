# Phase 6 M2.1正式测试冻结审计绑定修复

## 结论

PR #72合并后、正式测试启动前的真实只读预检正确停止，错误为`PR #70 freeze audit boundary mismatch`。截至停止时，正式测试输出目录不存在，场景生成数、Gurobi调用数和正式测试run数均为0。

根因是正式runner把PR #70冻结审计的生命周期字段错误读取为`execution_boundaries`；PR #70实际、已哈希保护的模式使用`authorization`。旧测试只验证待审批文件会被拒绝，没有让PR #72新授权贯穿到该真实审计接口，因此未覆盖模式不一致。

## 修复

runner现在通过独立验证函数严格读取PR #70的`authorization`，并同时要求：

- `selected_plan_freeze_authorized=true`；
- `formal_test_runner_implemented=false`；
- `formal_test_authorized=false`；
- `formal_extension_authorized=false`；
- 冻结文件SHA-256与PR #70审计完全一致。

测试直接读取真实PR #70审计，验证合法记录通过，并验证错误字段名及四项生命周期篡改全部被拒绝。

## 授权影响

本修复不改变数学模型、正式矩阵、统计协议或五类实验指纹，但会改变正式测试编排器哈希。PR #72授权仍永久记录其受审runner身份；当前修复后的runner与该身份不同，因此旧授权会在来源制品读取、场景生成和Gurobi调用前因编排器哈希不一致而拒绝。

本PR不得更新或迁移旧授权。合并后必须另建独立重新授权PR，再由用户明确授权完整10条正式测试批次。

## 执行边界

```text
formal_test_runs=0
scenario_generation_count=0
gurobi_call_count=0
algorithm_performance_runs=0
M0_E3_runs=0
formal_test_authorized_for_fixed_runner=false
```

科学配置、E3、family、runner配置和实验环境指纹均保持不变。正式测试输出目录`outputs/phase6_m2_1_formal_test_v1_0`不存在。

