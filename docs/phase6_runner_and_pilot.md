# 阶段6生成器、运行器与试运行协议

## 当前边界

阶段6runner已经实现，但精简矩阵
`phase6_streamlined_experiments_v2_0`仍处于
`candidate_for_freeze_pending_review`。不得运行正式种子。

正式授权要求：

1. 矩阵、runner和实验族执行器通过代码审查；
2. V1、V2、P1、P2各三个当前指纹pilot完整；
3. E1–E5均有量纲一致的实测投影；
4. 总工时与单实验族门槛通过；
5. 受审提交把矩阵状态改为`frozen_for_formal_execution`；
6. 投影明确记录`formal_execution_authorized=true`。

## 唯一运行环境

```text
D:\新建文件夹\项目交付\阶段3-4修复同步\phrase3\.venv-gurobi\Scripts\python.exe
```

只允许：

```text
Python 3.12.10
gurobipy 13.0.2
Gurobi Optimizer 13.0.2
Pyomo gurobi_direct
Threads = 1
```

Gurobi版本预检在场景生成前执行。禁止HiGHS和求解器回退。

## 受控生成器

`src/phase6_protocol.py`只接受：

```text
matrix_id = phase6_streamlined_experiments_v2_0
generator_protocol = phase6_controlled_synthetic_v1_0
NumPy = 2.5.1
```

它负责：

- 校验D0历史源文件哈希；
- 确定性解析V1–P2档位；
- 重算参考预算；
- 固定PCG64DXSM抽样顺序；
- 生成需求、应急价格和供应相关场景；
- 校验正式预算序列和正式种子选择。

D0保留六个历史绝对预算；V1–P2使用三个预算
`0.90/1.10/1.30 B_ref`。

## 运行入口

```powershell
.\.venv-gurobi\Scripts\python.exe -m src.run_phase6 `
  --config configs/phase6_runner.yaml `
  --output outputs `
  --tier V1 `
  --seed 2026072001 `
  --mode pilot `
  --run-id <NEW_RUN_ID>
```

只允许恢复`running`或`interrupted`的非终态checkpoint：

```powershell
.\.venv-gurobi\Scripts\python.exe -m src.run_phase6 `
  --config configs/phase6_runner.yaml `
  --output outputs `
  --tier V1 `
  --seed 2026072001 `
  --mode pilot `
  --run-id <INTERRUPTED_RUN_ID> `
  --resume
```

失败和超时为不可变终态。诊断重试必须使用新run ID，并记录
`parent_run_id`。

## 时限与失败保留

每档执行：

- 单次Gurobi调用时限；
- 单算法单预算外部watchdog；
- 单算法完整计划预算序列watchdog。

V1–P2的序列时限等于三个单预算时限；D0等于六个历史预算时限。

C&CG每次迭代原子写入progress文件，包含迭代日志、场景池、LB、UB、
gap和最坏场景。父进程超时后读取并保存这些字段。

当任一冷/热算法失败：

- 已完成预算保留`optimal`；
- 当前预算保留真实失败或超时状态；
- 后续预算记录`not_run_after_pair_sequence_failure`；
- 未执行的技术重复也生成显式状态行；
- 命令行写完诊断后非零退出。

## 技术重复与执行顺序

- V1：1次；
- V2：3次；
- P1：1次；
- P2：1次。

预算之间交替`cold -> warm`和`warm -> cold`。技术重复先取中位数，
不能作为独立样本。

## 锁与并发

- 每个run目录使用跨进程全生命周期排他锁；
- registry、性能表、失败表和投影使用共享聚合锁；
- 同一run ID不能同时执行或在原进程存活时恢复；
- 正式计时必须串行，禁止并行污染。

## 输出

每个运行写入：

```text
outputs/experiments/phase6/runs/<run_id>/
  resolved_run.json
  training_scenarios.csv
  checkpoint.json
  result.json
  budget_comparison.csv
  ccg_iterations.csv
  manifest.json
  workers/
```

全局输出：

```text
outputs/experiments/phase6/
  run_registry.csv
  failure_registry.csv
  algorithm_performance.csv
  pilot_throughput_projection.json
```

Manifest保存矩阵、科学配置、runner和E3代码指纹，以及Git、Python、
依赖、Gurobi、线程和硬件信息。原始实验输出默认不提交Git。

Phase 6在场景生成前逐项读取`requirements-gurobi-lock.txt`，并用已安装
发行版元数据核验所有精确版本。任一包缺失或版本不一致都会在生成场景前
拒绝运行；CI也直接从该锁文件安装依赖。

正式P2还必须读取`scale_advancement.json`，验证P1来源、P2目标、科学
配置、runner和E3组件指纹，以及完成率和运行时间两项门槛。该检查发生在
P2场景生成之前。

## 安全状态查询

不得用PowerShell `ConvertFrom-Json`读取大型结果。统一使用：

```powershell
.\.venv-gurobi\Scripts\python.exe -m src.phase6_status `
  --output outputs `
  --run-id <RUN_ID>
```

runner每次保存checkpoint或最终结果时同步写入小型
`status_summary.json`。状态工具只读取该sidecar、manifest和CSV元数据，
不解析大型result/checkpoint；失败摘要只保留白名单字段并截断消息。该命令
只输出有硬上限的摘要。

## 旧试运行的处理

旧HiGHS结果永远不进入Gurobi门槛。旧矩阵和旧科学指纹的Gurobi pilot
也不会进入精简矩阵投影。它们可以保留为历史正确性或诊断证据，但不能
替代新版pilot或混入正式计时。

精简矩阵仍要求四档×三个pilot种子，共12条预算序列；但每条序列只有
三个预算，且除V2外只有一次技术重复，计算量显著降低。
