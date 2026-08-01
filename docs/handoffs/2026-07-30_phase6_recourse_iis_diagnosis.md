# Phase 6 Recourse IIS Diagnosis

## 诊断范围

本诊断使用合并 PR #12 后的 `main` 提交
`5abb3f907b001871c03ab9e783a33a09f99ab6f6`，从三个 E4 pilot 各选取
一个真实样本外不可行场景。所有模型均使用原第一阶段方案、原配对测试
种子和相同场景生成协议重建；没有运行新 pilot，也没有删除或覆盖旧 run。

环境固定为 Gurobi Optimizer 13.0.2、gurobipy 13.0.2、
Pyomo `gurobi_direct`、`Threads=1`。三个场景的标准化状态和 Gurobi
原始终止条件均为 `infeasible`，不是超时、求解器失败或
`infeasible_or_unbounded`。

## 复现与 IIS

| Pilot seed | Test seed | Scenario | 原 E4 不可行数 | IIS 约束 | IIS 下界 | 不可约 IIS |
|---:|---:|---|---:|---:|---:|---|
| 2026072001 | 2036072001 | `s0028` | 60 | 4 | 11 | 是 |
| 2026072002 | 2036072002 | `s0113` | 40 | 9 | 16 | 是 |
| 2026072003 | 2036072003 | `s0014` | 93 | 9 | 16 | 是 |

三个 IIS 都包含：

- 固定采购或上期库存决定可用量的 `available_balance`；
- 非最大库龄只能在消费和期末库存之间分配的 `age_flow`；
- 低需求限制可消费量的 `demand_balance`；
- 限制未到期结转库存的 `storage_capacity`；
- 相关采购、消费、库存和缺货变量的非负边界。

第一个 IIS 在第 0 期即出现：可用新库存为 `224.4883681`，需求仅
`50.4115274`，而期末容量为 `165.0`。即使把需求全部用库存满足，
仍有约 `9.07684` 单位未到期库存既不能结转也不能退出。其余两个 IIS
跨相邻时期显示相同结构。

完整哈希、约束名称和变量边界映射见
`2026-07-30_phase6_recourse_iis_audit.json`。IIS 已在模型变更前提交
`5abb3f9` 上用 `symbolic_solver_labels=True` 重新导出；审计 JSON 对每个
Gurobi 符号名称记录精确的 Pyomo `ComponentData.name`。Gurobi 导出的
精简 IIS 文件位于 `docs/handoffs/phase6_recourse_iis/`，并由
`.gitattributes` 按原始字节保存；文件只含 Gurobi 返回的不可约 IIS，
不含完整场景或大型求解日志。这里 `IISMinimal=1` 表示删除其中任一成员
可能破坏该 IIS 的不可行性，不表示它是所有 IIS 中基数最小的一个。
自动测试会同时核验三个文件的 SHA-256、符号名称与映射。

## 根因判定

诊断门槛通过。真实根因是：

> 固定第一阶段采购在低样本外需求下形成未到期剩余库存；旧模型没有
> 提前报废、捐赠或调出通道，导致库龄流转和期末仓储容量约束冲突。

IIS 没有指向第一阶段预算、应急预算、场景索引、服务约束或求解状态
分类错误。因此可以实施任务规定的最小提前处置修复。

## 修复边界

对非最大库龄增加有正惩罚的 `early_disposal`；最大库龄仍进入
`expired_waste`。两者沿用同一 `waste_penalty[item]`，不使用 Big-M。
不改变第一阶段预算等式、应急储备定义、C&CG/SPW-C&CG oracle、终止
条件或场景池逻辑。

该发现只作为 pilot 暴露的模型边界和结构修复动机，不宣称为论文创新。
