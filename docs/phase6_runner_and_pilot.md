# 阶段6受控生成器、实验运行器与试运行协议

## 当前边界

本次实现的是阶段6正式实验的执行基础设施，不代表正式实验已经启动或完成。
`configs/phase6_experiment_matrix.yaml` 当前仍为
`candidate_for_freeze_pending_review`，因此运行器会拒绝 `formal` 模式。只有在：

1. 本实现通过代码审查；
2. V1、V2、P1、P2 的三个试运行种子全部完成；
3. E1、E2、E4、E5 的实验族执行器和有量纲实测速率已经实现；
4. E1–E5 预计总工时门槛通过；
5. 实验矩阵状态由受审提交更新为 `frozen_for_formal_execution`；

之后，才允许使用正式训练种子。

正式入口在生成任何场景前同时核验矩阵状态，以及投影文件中的科学配置
SHA-256、runner 配置 SHA-256、E3 组件代码 SHA-256、12项试运行覆盖、
失败/重复记录、`compute_gate_passed` 和 `formal_execution_authorized`。
任一条件不成立都拒绝执行。原始矩阵文件 SHA-256 仍写入 manifest 供追溯，
但矩阵状态和修订日期不参与科学配置哈希；因此受审的状态切换不会让既有试运行
失效。E3 组件哈希只覆盖生成器、模型、C&CG、worker、runner 和这些组件的
依赖声明，新增其他实验族执行器不会使 E3 试运行失效。

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

只允许恢复 `running` 或 `interrupted` 的非终态运行：

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

`failed`、超时或其他终态 checkpoint 不可恢复成成功。诊断重试必须使用新
`run_id`，并记录失败父运行：

```powershell
python -m src.run_phase6 `
  --config configs/phase6_runner.yaml `
  --output outputs `
  --tier V1 `
  --seed 2026072001 `
  --mode pilot `
  --run-id pilot_v1_diagnostic_001 `
  --parent-run-id pilot_v1_failed_001
```

运行器实现以下控制：

- 单次求解器调用时限仅传递到 Gurobi；
- 单预算完整 C&CG 由独立子进程墙钟看门狗强制执行；
- 冷启动和热启动的六预算序列分别累计墙钟时限；
- 主进程超时时终止该工作进程及其子进程；
- C&CG 每完成一次迭代就原子写入 heartbeat，记录迭代日志、当前场景池、
  LB、UB、gap 和最坏场景；外部超时后父进程读取并保留该文件；
- V1/V2/P1 按矩阵执行三次技术重复，先取墙钟中位数；
- 预算间交替冷/热执行顺序；
- 每个已完成预算配对后原子写入 checkpoint；
- 恢复时校验矩阵文件、科学配置、runner 配置、E3 组件、档位、种子、模式、父运行和
  预算序列指纹；
- 只有最优且冷/热目标一致的热启动状态可以传递；
- 失败运行在 `comparisons`、预算表和逐算法性能表中保留全部六个计划预算：
  已完成预算为 `optimal`，当前预算记录实际失败/超时状态，后续预算记录为
  `not_run_after_pair_sequence_failure`；未执行的算法重复也保留显式状态；
- 同一 `run_id` 的整个生命周期由 run 目录排他锁保护，活动运行结束前禁止
  第二个进程执行或 `--resume`；
- 全局 registry、性能表、失败表和投影文件使用同一个成熟的跨平台文件锁，
  防止多个本地主 runner 的读取—修改—替换互相覆盖。

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
    *_progress.json
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
| 2026072001 | 0 | 59 | 16 | 50.091 | 18.305 |
| 2026072002 | 0 | 44 | 12 | 38.175 | 15.028 |
| 2026072003 | 1.819e-12 | 55 | 14 | 46.373 | 16.466 |

以上结果由实现提交 `28340e5182affb18bd778bc9dc6420b966e71a96` 重新生成；
科学配置哈希为
`7d9e0df1b299fb11cff8268a01a557493bbf32e038ae056c8ff203d1d7e2f0c2`，
E3 组件哈希为
`1f622db5e87e592568d86e8a5467aab8493344cb6abc9252f3597f3fba1d831d`。
三次运行的 manifest 均记录同一提交和上述两类哈希。结果只作试运行描述，
不进行显著性推断。当前完整试运行覆盖率为
`3/12` 个“档位—种子”运行，尚缺 V2、P1、P2 各三个种子。因此
`pilot_throughput_projection.json` 正确返回
`insufficient_pilot_coverage` 和
`formal_execution_authorized=false`，不得据此启动正式种子。

即使未来12项算法试运行全部完成，在 E1/E2/E4/E5 的实验族执行器和有量纲
速率尚未实现时，投影状态仍必须是 `projection_incomplete`，不得用“算法实例数
除以主问题/小时”估算这些实验族，也不得产生正式授权。

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
