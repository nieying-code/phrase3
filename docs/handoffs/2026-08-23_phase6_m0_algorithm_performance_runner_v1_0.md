# Phase 6 M0 E3算法性能一次性执行器交接

日期：2026-08-23

## 结论

本PR在PR #75合并后的M0科学基线上建立一次性、受控的E3算法性能执行器，并直接冻结执行授权。冻结矩阵独立复算为21条primary run、63个预算配对和246次算法执行。本PR没有生成场景、没有调用Gurobi求解，也没有运行算法性能实验。

## 论文职责边界

- 已有E1正式证据负责扩展式与标准C&CG的目标正确性比较。
- 本批E3只执行冻结矩阵中的`standard_ccg_cold`与`spw_ccg_warm`，用于冷/热目标一致性和效率比较。
- V2的三次技术重复只用于降低计时噪声；统计单位仍为随机种子。
- P2仅作描述性压力测试。
- M2负责储备机制和样本外证据；本批不测量M2算法速度，也不得把M0加速比例表述为M2实测结果。

这里没有新增`spw_ccg_cold`，也没有改变既有实验矩阵。SPW-C&CG的“warm”是冻结的跨预算场景池热启动实现；标准C&CG是相同模型、相同场景和相同预算下的冷启动基线。

## 冻结工作量

| 档位 | 正式种子数 | 技术重复 | 每个种子的执行数 | 总执行数 |
|---|---:|---:|---:|---:|
| V1 | 3 | 1 | 6 | 18 |
| V2 | 10 | 3 | 18 | 180 |
| P1 | 5 | 1 | 6 | 30 |
| P2 | 3 | 1 | 6 | 18 |
| 合计 | 21条primary | — | — | 246 |

每条primary包含0.9、1.1、1.3三个预算；每个预算包含标准C&CG冷启动和SPW-C&CG跨预算热启动。正式种子来自冻结矩阵，依次使用`2026072401`起的前N个种子。

## 安全执行协议

- 独立命名空间：`phase6_m0_e3_algorithm_performance_v1_0`。
- 独立输出根：`outputs/phase6_m0_e3_algorithm_performance_v1_0/formal/primary`。
- 只允许从包含本PR合并树的干净`main`执行。
- runner只读验证`branch.main.remote=origin`、`branch.main.merge=refs/heads/main`且`HEAD=refs/remotes/origin/main`；用户须在执行前自行完成`fetch`、切换`main`和`pull --ff-only`。
- CLI必须显式提供`--authorize-m0-e3-algorithm-performance`和全新run ID前缀。
- primary只能在空命名空间中按V1→V2→P1→P2严格串行完整执行。
- 每条run继续由既有Phase 6 runner记录目标、界、gap、迭代、主/子问题调用、墙钟、内存、场景身份以及Git/环境指纹。
- 任一非最优、超时、异常、无效或重复primary立即停止；失败primary永久阻断本批门槛。
- 诊断必须指定同一case的失败primary作为`parent_run_id`并使用新run ID；诊断不能修复primary门槛。
- 状态工具只读取不超过16 KiB的小型状态摘要。

批准范围精确为：

```text
M0_E3_algorithm_performance_authorized=true
M2_formal_authorized=false
M2_formal_OOS_authorized=false
M2_1_authorized=false
other_formal_experiments_authorized=false
```

## 证据绑定

执行器逐字节绑定：

- PR #33最终计算门槛审计；
- PR #34的E1正式正确性审计；
- 冻结实验矩阵及既有E3 runner；
- 新的一次性编排器、CLI、状态工具和approval；
- Python 3.12.10、Gurobi/gurobipy 13.0.2、`gurobi_direct`、`Threads=1`及冻结环境指纹。

目标一致性继续使用矩阵冻结的绝对/相对容差，不增加额外余量。projection会从最终化run制品重新计算63个预算配对和246次执行，并拒绝非有限、负值或超过各预算冻结容差的目标差。

## 本PR验证与停止边界

本地专项测试、完整普通回归、Phase 5测试、Windows复现测试、真实实验机只读预检和CI结果记录在PR正文。最终提交和tree也只记录在PR正文，避免文件自引用。

本PR计数：

```text
scenario_generation_count=0
gurobi_call_count=0
algorithm_performance_runs=0
M2_performance_runs=0
M2_1_runs=0
```

Draft PR复审并由用户手动合并后，合并本身即授权严格串行运行完整246次执行，不再创建第二个授权PR。完成全部批次或首次异常后立即停止并创建独立结果Draft PR。
