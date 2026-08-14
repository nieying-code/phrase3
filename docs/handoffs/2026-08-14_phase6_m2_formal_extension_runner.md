# Phase 6 M2 正式扩展 pilot runner 交接

## 交付范围

本分支基于 PR #52 合并后的 `main`（`20af98b522d498c6ffa8a384f819f307f686ddfe`），只实现 M2 正式扩展的技术 pilot runner、受控配置、状态工具和自动测试。本分支没有生成真实场景、没有调用 Gurobi，也没有运行 pilot、正式扩展实验、算法性能实验或 M0 E3。

## 冻结 pilot

- 机制 pilot：3 个训练种子，每个种子运行 `beta=1.1/C0,C1,T03` 与 `beta=1.3/C0,T03`，共 15 条 primary run。
- OOS 吞吐量探针：训练种子 `2026081601`、独立测试种子 `2026081701`，`beta=1.1/T03`，读取该机制 run 最终化的 5 个第一阶段方案，各评价 2000 个共同测试场景。
- 主运行必须从空的独立输出根一次串行执行完整 16 条；不允许任意选择部分 primary。
- 诊断运行必须使用一个 case、新 run ID 和同 case 的失败 primary `parent_run_id`。

## 安全与审计闭环

运行前同时验证：显式 CLI 授权、冻结状态、批准文件、五类指纹、父级 PR #51 证据、Git 执行输入和锁定环境。结果按 `result → manifest → registry → projection` 最终化；run ID 为不可变终态；registry、projection 和完整批次均使用跨进程锁。

机制 projection 从数值独立复算自主储备比例，并核验 100 个训练场景、双物资参考预算、Gurobi 13.0.2、`gurobi_direct`、`Threads=1`、完整扩展式储备区间、端点精确补救、四种重新优化的固定自主储备策略、C0 等价和共同随机数。OOS projection要求 5 个哈希锁定方案各完成 2000 个精确补救评价且零不可行、零求解失败。

即使 pilot 与工时门槛全部通过，runner 也只能输出：

```text
next_decision=permit_separate_formal_freeze_PR_only
formal_extension_authorized=false
```

## 批准指纹

```text
scientific_config_sha256=fec4e4dde521692767f9ba48ec6809528f87856c59d2be0a082bcfa360980565
e3_component_sha256=8c7230752ad73fc6360746061fb887d0ff3f0ad29b86f03bb007feb596c9a62b
family_component_sha256=54ed1bac9c169e576fc694782c48c6e2d7641870b412fbe48743fb81b4977d2e
runner_config_sha256=76f54b5394406715b1974db1be6db49805f7c9458f8f886efc1010c7421fd3f0
environment_sha256=b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af
```

## 当前停止边界

```text
mechanism_pilot_runs=0
OOS_probe_runs=0
formal_mechanism_runs=0
formal_OOS_runs=0
algorithm_performance_runs=0
M0_E3_runs=0
scenario_generation_count=0
gurobi_call_count=0
formal_extension_authorized=false
```

最终 PR head、CI 链接和完整测试数量记录在 PR 正文，避免审计文件自引用。
