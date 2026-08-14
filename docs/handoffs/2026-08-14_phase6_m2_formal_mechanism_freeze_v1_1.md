# Phase 6 M2 正式机制批次冻结与安全执行器 v1.1

## 结论

本 PR 只建立正式机制批次的冻结授权和安全执行入口，不运行任何科学实验。授权范围严格限定为50条机制运行；正式 OOS、算法性能实验和 M0 E3 均保持关闭。

## 为什么使用独立正式编排层

PR #56 的15条机制 pilot和1条OOS探针使用的科学内核已经通过复审。现有命令行入口只允许 pilot，不能直接用于正式种子。本 PR 不修改该科学内核，也不修改已经批准的五类指纹；新增的正式编排文件由独立 `formal_orchestrator_sha256` 保护。

正式执行前同时要求：

1. PR #56紧凑审计、D盘pilot projection和registry字节哈希完全一致；
2. `pilot_compute_gate_passed=true`；
3. pilot仍记录`formal_extension_authorized=false`和`permit_separate_formal_freeze_PR_only`；
4. 五类科学、组件、runner和环境指纹保持批准值；
5. 正式编排指纹匹配；
6. 显式提供`--authorize-formal-mechanism-execution`；
7. 源码、配置和依赖输入干净且均为Git已跟踪文件。

## 冻结正式矩阵

- 10个正式训练种子：`2026081401`至`2026081410`；
- `beta=1.1`：C0、C1、T03，共30条；
- `beta=1.3`：C0、T03，共20条；
- 合计50条；
- 严格串行，不允许部分primary批次、适应性停止或观察结果后修改矩阵。

正式输出位于：

```text
outputs/phase6_m2_formal_extension_v1_1/formal/mechanism
```

pilot registry和projection只读，正式运行只更新独立的formal registry和progress。任一失败、超时、中断、无效制品、重复primary或最终化错误均阻止批次门槛；诊断重试必须使用新run ID和同case失败parent。

## 停止边界

50条全部完成后，执行器最多输出：

```text
formal_mechanism_gate_passed=true
next_decision=permit_mechanism_results_review_only
formal_OOS_authorized=false
```

它不会启动或授权正式OOS。正式机制结果必须形成独立结果PR并通过复审，之后才能另行设计和授权10万次样本外评价。

## 本PR验证范围

测试覆盖50项笛卡尔积、显式授权、五类指纹不变、正式编排指纹、pilot证据哈希、禁止部分primary、空命名空间、失败后停止、失败primary不可被成功重复掩盖、共同随机数门槛、不可变制品、最终化异常及16KiB有界状态。

本 PR 中：场景生成0次、Gurobi调用0次、正式机制运行0条、正式OOS运行0条。最终PR head和CI记录在PR正文，避免文档自引用。

