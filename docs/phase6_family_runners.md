# Phase 6 E1/E2/E4/E5 执行器

## 目的与边界

本模块补齐精简版 Phase 6 矩阵中除 E3 冷/热 C&CG 比较以外的四类实验：

- E1：全场景扩展式与标准 C&CG 的目标一致性；
- E2：确定性、零储备、三个固定储备比例和内生储备的统一训练场景精确评价；
- E4：固定 E2 第一阶段方案，在独立测试场景上进行样本外精确补救评价；
- E5：11 个 OFAT 配置和 4 个“保质期 × 供应冲击”交互配置。

这些执行器位于独立组件中，不修改 E3 的模型、C&CG、SPW-C&CG、worker 或 runner。因此，已经完成且指纹一致的 V1 E3 pilot 不会因本模块失效。

相对完全补救科学模型修订已经通过 PR #14 复审并合并，矩阵 v2.1 随后由
独立受审提交重新冻结为 `frozen_for_formal_execution`。这只解除 pilot
入口的候选状态阻断；所有正式种子仍须等待完整 E3/family pilot、计算量
投影和 `formal_execution_authorized=true`。

## 入口与环境

唯一允许的解释器为：

```text
D:\新建文件夹\项目交付\阶段3-4修复同步\phrase3\.venv-gurobi\Scripts\python.exe
```

求解环境固定为 Gurobi Optimizer 13.0.2、`gurobipy==13.0.2`、Pyomo `gurobi_direct` 和 `Threads=1`，依赖版本逐项核对 `requirements-gurobi-lock.txt`。

受审后运行单个 family pilot 的入口为：

```powershell
.\.venv-gurobi\Scripts\python.exe -m src.run_phase6_family `
  --matrix configs/phase6_experiment_matrix.yaml `
  --config configs/phase6_family_runner.yaml `
  --output outputs `
  --family E1 `
  --seed 2026072001 `
  --mode pilot `
  --run-id pilot_family_e1_2026072001
```

本提交没有运行这些 pilot。后续必须按每个种子的 E1 → E2 → E4 → E5 顺序串行执行；代码会在 worker 启动前强制检查前序 family、三类科学指纹和环境指纹。

## Pilot 工作单位

每个 pilot 种子包含：

- E1：V1 中间预算的 1 个完整一致性计划；
- E2：V2 中间预算的 6 个策略计划；
- E4：复用同种子 E2 的内生储备方案，完成 1 个 2,000 场景样本外计划；
- E5：V2 中间预算的基准配置和 1 个交互压力配置，共 2 个计划。

三个 pilot 种子共形成 12 条 family run 和 30 个完整工作单位。投影器按“完整计划/小时”分别估计 E1、E2、E4、E5，不再以主问题次数错误替代不同实验族的工作量。

## 结果语义

E1 仅在以下条件全部满足时记为 `optimal`：

1. 扩展式求解最优；
2. 标准 C&CG 收敛且终止状态最优；
3. 两者目标满足冻结的绝对和相对容差；
4. 两者的全部训练场景独立补救评价均最优。

E2 的六类策略全部在相同完整训练场景上重新求解独立补救模型。确定性模型的原生目标不直接参与鲁棒目标比较。相对完全补救修订后，六类策略中任何一个出现 `infeasible_recourse` 都表示结构不变量被破坏：该工作单元必须记为 `unexpected_infeasible_recourse`，保留原生方案、不可行场景数、工作单元结果及其 SHA-256，但停止当前 family 序列并拒绝通过门槛。不得将其记为 `optimal`、伪装成求解失败或使用 Big-M 伪成本。内生储备方案不劣于最佳固定比例方案仍作为结构正确性门槛，而非经验创新结论。

E4 禁止在测试集重新优化第一阶段方案。每个场景只能属于 `optimal`、`infeasible` 或 `solver_failure` 三类之一，并强制：

```text
N_total = N_optimal + N_infeasible + N_solver_failure
```

只要存在补救不可行或求解失败，总成本均值、分位数和 CVaR 等聚合量即记为不可用，不使用 Big-M 伪成本。进一步地，只要 `infeasible_scenario_count > 0`，E4 工作单元必须记为 `unexpected_infeasible_recourse`，不得记为 `optimal`，并保留诊断制品、停止当前 family 序列和拒绝 family gate。求解器失败继续使用独立的 `oos_solver_failure` 状态。服务水平按所有场景总需求加权；零储备时储备利用率为 `null`。

库存退出量分为 `expired_waste`、`early_disposal` 和二者之和
`total_disposal`。兼容指标 `waste`/`mean_waste` 明确定义为总退出量，
不得与两个分量再次相加。相对完全补救修订后，有限非负场景原则上应均
可行；状态分类仍保留，用于发现模型、数据或求解异常。

E5 对每个完整配置重新生成训练场景并求解内生储备扩展式，配置之间不共享被修改的数据对象。

矩阵处于 `candidate_for_freeze_pending_review` 时，E3 pilot 和全部 family pilot 均在计划解析或场景生成前被拒绝。只有独立受审提交把状态恢复为 `frozen_for_formal_execution` 后，才允许使用全新 run ID 运行 pilot。

## 失败保留与监控

每条 run 是不可变终态。失败计划会保留实际状态，后续计划写为 `not_run_after_family_failure`；不得用相同 run ID 覆盖失败结果。

主要文件位于：

```text
outputs/experiments/phase6/
  family_runs/<run_id>/
    checkpoint.json
    status_summary.json
    result.json
    manifest.json
    workers/
  family_run_registry.csv
  pilot_throughput_projection.json
```

监控时只读取白名单化的小型摘要：

```powershell
.\.venv-gurobi\Scripts\python.exe -m src.phase6_family_status `
  --output outputs --run-id <run_id>
```

该工具不会解析 `result.json` 或 `checkpoint.json`，只报告摘要、文件大小和匹配进程，从而避免 PowerShell 读取大型 JSON 的问题。

## 指纹与正式门槛

family registry 和投影同时核验：

- 生命周期字段之外的科学矩阵哈希；
- family runner 配置文件哈希；
- E1/E2/E4/E5 独立组件代码哈希；
- 实际锁定依赖版本的环境哈希。

每个 family 必须恰好有三个无父运行标识、完整且最优的 pilot。缺失、失败或重复运行都会阻止投影通过。只有 E1–E5 全部获得有量纲一致的投影、E3 pilot 覆盖完整、总工时与单 family 工时门槛通过且矩阵已冻结时，`formal_execution_authorized` 才能为 `true`。
