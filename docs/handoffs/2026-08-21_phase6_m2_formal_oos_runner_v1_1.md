# Phase 6 M2 正式样本外冻结与安全执行器 v1.1

## 结论

本提交在PR #58合并后的`main`上冻结并实现正式样本外评价执行器。本提交没有生成场景、调用Gurobi、运行正式OOS、算法性能实验或M0 E3。

正式OOS仍使用已受审的M2科学设计和五类实验指纹。新增的只是独立编排层：

```text
namespace = phase6_m2_formal_oos_v1_1
output_root = outputs/phase6_m2_formal_oos_v1_1
formal_subdirectory = formal/OOS
```

它读取但绝不修改：

```text
outputs/phase6_m2_formal_extension_v1_1/formal/mechanism
```

## 冻结批次

10个正式训练种子与10个独立测试种子按列表位置一一配对：

```text
2026081401–2026081410 ↔ 2026081501–2026081510
```

每组固定使用`beta=1.1/T03`，读取五种已最终化第一阶段方案：

1. 内生储备（完整扩展式`R_min_opt`端点）；
2. 零自主储备；
3. 固定自主储备10%；
4. 固定自主储备30%；
5. 固定自主储备50%。

每个训练—测试种子对内五种策略共享同一组2000个测试场景，禁止在测试集重新优化：

```text
10 primary OOS runs × 5 plans × 2000 scenarios = 100000 exact recourse evaluations
```

## PR #58来源绑定

预检同时验证：

- PR #58紧凑审计文件的逐字节SHA-256；
- D盘正式机制registry和progress的逐字节SHA-256；
- 审计中记录的registry/progress哈希与本地制品一致；
- 五类科学指纹和正式机制编排器指纹一致；
- 50/50正式机制run完整且异常集合为空；
- 10条`beta=1.1/T03`来源run的result和manifest哈希；
- 每个来源run的五种方案储备金额、采购哈希、训练目标、训练场景哈希及最终方案制品哈希。

审批文件与本地registry同时被替换、但PR #58审计保持不变时，预检仍会拒绝。OOS worker只能读取经过上述验证的最终方案，不允许重求解、替换或跨run引用。

## 运行安全

- 缺少`--authorize-formal-oos-execution`时，在读取科学证据和生成场景前拒绝；
- primary必须一次运行完整10组，不能选择子集；
- 严格串行，一个run完全最终化后才进入下一run；
- 全新primary批次要求OOS命名空间为空；
- run ID不可覆盖；失败、超时、中断和成功均为不可变终态；
- 诊断重试必须使用一个case ID、新run ID和失败primary的`parent_run_id`；
- 任一非最优、超时或异常立即停止后续run；
- 预检精确锁定单次Gurobi调用120秒、每个策略7200秒墙钟上限和`Threads=1`；
- 每个策略逐场景检查7200秒截止时间，并用剩余墙钟时间收紧下一次Gurobi调用；超限形成不可变`timeout`终态，不能进入下一策略或下一run；
- CLI只有在10条run均最优且最终`formal_OOS_gate_passed=true`时才返回成功；
- result、manifest、registry和progress均使用原子写入和跨进程锁；
- 状态工具只读取不超过16 KiB的小型摘要，不解析大型结果或checkpoint；
- 即使100000次评价全部通过，runner也只输出`permit_OOS_results_review_only`，算法性能实验仍未授权。

## 指纹边界

新增正式OOS编排器具有独立哈希。科学配置、E3组件、family组件、pilot runner配置和批准实验环境五类指纹保持PR #58受审值，不迁移或重写任何既有结果。

## 本地验证

- 语法检查通过；
- 正式OOS runner专项测试通过；
- 完整回归和CI结果将在本PR最终正文记录，避免文档自引用。

## 停止边界

本PR中的执行计数为：

```text
formal_OOS_primary_runs=0
formal_OOS_plans=0
formal_OOS_recourse_evaluations=0
algorithm_performance_runs=0
M0_E3_runs=0
```

本PR只能作为后续人工授权的运行基础，不能自动启动正式OOS。
