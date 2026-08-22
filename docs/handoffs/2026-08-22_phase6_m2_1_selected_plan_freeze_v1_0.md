# Phase 6 M2.1 入选方案冻结（v1.0）

## 结论

本PR只把PR #69已经复审的10个验证集入选方案冻结为不可变身份，并预注册一次性正式测试的工作量和统计口径。没有实现或开放正式测试runner，也没有读取保留测试种子。

冻结结果：

- 最大端点：8组；
- 最小端点：2组；
- 中点：0组；
- 10个正式测试种子；
- 6种策略；
- 60个正式测试方案；
- 预计120,000次精确补救评价。

每个入选方案均锁定来源run、case、训练/验证/测试种子、候选ID、最终方案制品哈希、常规采购哈希、储备金额、精确训练目标和训练场景集合哈希。

## 证据闭环

冻结配置逐字节绑定PR #69紧凑审计、正式训练—验证registry、projection及`selected_plan_identity_mapping_sha256=df515f14931e...`。专项测试会从PR #69的10条run重新计算选择结果和映射，禁止依赖手工填写的候选ID。

## 正式测试协议

对每个训练—验证—测试三元组比较：M2最小端点、M2.1验证入选端点、零自主储备和固定自主储备10%、30%、50%。六种策略共享同一个全新正式测试场景集合，禁止在测试集重新优化或重新选择方案。

唯一主要确认量仍是M2.1相对M2的OOS CVaR95配对差。Bootstrap、Wilcoxon和结果判定规则均保持原冻结设计，不因验证结果改变。

## 停止边界

```text
selected_plan_freeze_authorized=true
formal_test_runner_implemented=false
formal_test_authorized=false
formal_extension_authorized=false
scenario_generation_count=0
gurobi_call_count=0
formal_test_runs=0
```

下一步只能另建正式测试runner Draft PR，实现证据只读绑定、空输出命名空间、严格串行、失败即停和一次性测试集访问门槛。该runner完成复审前不得运行正式测试。

## 本地验证

- 冻结与原设计专项：14 passed；
- 普通回归：567 passed；
- Phase 5：6 passed；
- Windows复现：16 passed；
- `compileall`与`git diff --check`通过。
