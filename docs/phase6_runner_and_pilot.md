# 阶段6受控生成器、实验运行器与试运行协议

## 当前边界

本次实现的是阶段6正式实验的执行基础设施，不代表正式实验已经启动或完成。
`configs/phase6_experiment_matrix.yaml` 当前仍为
`candidate_for_freeze_pending_review`，因此运行器会拒绝 `formal` 模式。只有在：

1. 本实现通过代码审查；
2. V1、V2、P1、P2 的三个试运行种子全部完成；
3. 预计总工时门槛通过；
4. 实验矩阵状态由受审提交更新为 `frozen_for_formal_execution`；

之后，才允许使用正式训练种子。

## 受控数据生成

`src/phase6_protocol.py` 是机器可读矩阵的严格执行器：

- 只接受矩阵 `phase6_formal_experiments_v1_3` 和生成协议
  `phase6_controlled_synthetic_v1_0`；
- 严格检查 NumPy `2.5.1` 和 PCG64DXSM 随机数协议；
- 按冻结抽取顺序生成共同灾害、物资、时期和特异噪声；
- 实现需求、应急价格和应急供应的相关变换、边界截断、库容、初始库存和惩罚规则；
- 为每个档位重新计算参考预算，D0 使用历史名义需求口径，V1–P4
  使用冻结生成器理论期望；
- 同一档位、种子和预算生成完全相同的数据。

## 运行与恢复

运行入口：

```powershell
python -m src.run_phase6 `
  --config configs/phase6_runner.yaml `
  --output outputs `
  --tier V1 `
  --seed 2026072001 `
  --mode pilot `
  --run-id pilot_v1_2026072001
```

恢复同一个运行：

```powershell
python -m src.run_phase6 `
  --config configs/phase6_runner.yaml `
  --output outputs `
  --tier V1 `
  --seed 2026072001 `
  --mode pilot `
  --run-id pilot_v1_2026072001 `
  --resume
```

运行器实现以下控制：

- 单次求解器调用时限传递到 HiGHS/Gurobi；
- 单预算完整 C&CG 由独立子进程墙钟看门狗强制执行；
- 冷启动和热启动的六预算序列分别累计墙钟时限；
- 主进程超时时终止该工作进程及其子进程；
- V1/V2/P1 按矩阵执行三次技术重复，先取墙钟中位数；
- 预算间交替冷/热执行顺序；
- 每个已完成预算配对后原子写入 checkpoint；
- 恢复时校验矩阵、runner 配置、档位、种子、模式和预算序列指纹；
- 只有最优且冷/热目标一致的热启动状态可以传递；
- 失败运行保留当前部分重复、已完成预算、失败层级和 worker 诊断，
  命令行返回非零状态。

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

全局输出包括：

```text
outputs/experiments/phase6/
  run_registry.csv
  failure_registry.csv
  algorithm_performance.csv
  pilot_throughput_projection.json
```

Manifest 保存矩阵、runner 配置、解析运行和训练场景的 SHA-256，以及
Git 状态、Python、依赖、求解器、线程、CPU 和内存信息。原始实验输出默认不提交
Git，避免把大规模场景和运行缓存混入代码审查。

## 当前试运行结果

D0 开发回归完成 6/6 个历史预算；预算 1000 的标准 C&CG 和
SPW-C&CG 目标均为 `3269.9644075814263`。

V1 的三个试运行种子均完成 6/6 个预算、冷/热各三次技术重复：

| 种子 | 最大冷/热目标差 | 冷启动代表迭代总数 | 热启动代表迭代总数 | 冷启动代表时间总和（秒） | 热启动代表时间总和（秒） |
|---:|---:|---:|---:|---:|---:|
| 2026072001 | 0 | 59 | 16 | 49.788 | 18.154 |
| 2026072002 | 0 | 44 | 12 | 38.152 | 14.942 |
| 2026072003 | 1.819e-12 | 55 | 14 | 46.515 | 16.408 |

以上只是试运行描述结果，不进行显著性推断。当前完整试运行覆盖率为
`3/12` 个“档位—种子”运行，尚缺 V2、P1、P2 各三个种子。因此
`pilot_throughput_projection.json` 正确返回
`insufficient_pilot_coverage` 和
`formal_execution_authorized=false`，不得据此启动正式种子。

## 尚未实现或尚未执行

- V2、P1、P2 的试运行与完整计算量门槛；
- 正式训练种子；
- E1 全场景扩展式金标准批量运行；
- E2 八策略统一训练评价与独立样本外评价；
- E4 储备机制和场景相似度统计；
- E5 敏感性与交互实验；
- 簇 bootstrap、图表和论文表格；
- 真实数据校准轨道。

这些内容应在完整试运行门槛通过后按独立受审任务逐步实现。
