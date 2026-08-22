# Phase 6 M2.1 正式训练—验证结果交接（v1.0）

## 执行结论

冻结的10组三元组已在 PR #68 合并后的代码树上严格串行完成。10/10 primary run 均为 `optimal`，30个候选方案全部完成验证集精确补救评价，共计60,000次，补救不可行和求解失败均为0。

机器门槛结果为：

```text
formal_training_validation_gate_passed=true
selected_plan_freeze_authorized=false
formal_test_authorized=false
formal_extension_authorized=false
```

因此本批只支持另建“入选方案冻结与正式测试授权”PR；当前不得读取或生成所保留的正式测试场景。

## 执行身份

- 执行提交：`adda64a395eb9752676d290e5c82ac59de068b68`
- 执行 tree：`71aeb9e93803db0fc0326373836b9c08403fbba4`
- Python：3.12.10
- Gurobi/gurobipy：13.0.2
- 接口：`gurobi_direct`
- Threads：1
- 工作树：已跟踪修改0，未跟踪执行输入0
- run ID 前缀：`m21formal_tv_v10_20260822`

五类指纹与 PR #68 批准值完全一致。

## 结果闭合

| 项目 | 结果 |
|---|---:|
| Primary runs | 10/10 optimal |
| 训练场景 | 10 × 100 |
| 验证候选 | 10 × 3 = 30 |
| 验证精确补救评价 | 30 × 2,000 = 60,000 |
| 最小端点入选 | 2 |
| 中点入选 | 0 |
| 最大端点入选 | 8 |
| 总墙钟时间 | 1,758.5159008 秒 |
| 最大单组三元组时间 | 180.4053727 秒 |
| 最大采样RSS | 164.359375 MiB |

验证选择严格使用冻结规则：先最小化验证集 CVaR95；在冻结容差内再比较平均成本；仍平局时选择更少储备。测试集指标没有参与选择。

## 证据边界

10个保留测试种子仅保存在配置身份中。每条结果均记录：

```text
test_scenario_count=0
test_results={}
test_scenario_identity=null
```

本批没有生成正式测试场景，没有运行正式测试、selected-plan freeze、算法性能实验或 M0 E3。大型原始结果继续保存在受控本地输出目录，GitHub仅提交紧凑证据和哈希。

## 科学解释边界

10组中有8组由验证集选择最大端点、2组选择最小端点、中点未入选。这说明正式验证结果与3组pilot全部选择最小端点的表现不同，端点选择机制具有实际作用；但正式测试集尚未打开，因此不能据此声称 M2.1 已改善测试集风险表现。

## 验证与停止

- 专项审计测试：4 passed；
- 完整普通回归：563 passed；
- Phase 5：6 passed；
- Windows复现专项：16 passed；
- Linux/Windows CI：待最终提交记录。

下一步只能在独立PR中冻结10个最终入选方案及其哈希，并继续保持正式测试关闭，直到该PR完成复审和人工合并。
