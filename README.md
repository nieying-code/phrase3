# 固定预算下易腐救灾物资两阶段鲁棒采购

本项目研究固定总预算在灾前常规采购与灾后应急储备之间的内生分配，并考虑多期库龄、到期浪费、仓储容量、需求波动、应急价格上涨和供应受限。

PR #1 的代码标签沿用了“阶段3”，但实际同时完成了原计划阶段3（全场景内生储备扩展式）和阶段4（标准有限场景 C&CG）：包括独立精确补救模型、完整有限场景 oracle，以及确定性/固定比例/内生模型的统一精确评价。当前已完成阶段5：在阶段4标准 C&CG 的基础上实现跨预算场景池热启动 SPW-C&CG，并对每个预算执行冷/热目标一致性验证。

## 模型

- `DeterministicModel`：分量均值场景下的确定性规划基线。
- `FixedReserveModel`：固定储备比例下的全训练场景鲁棒基线。
- `EndogenousReserveExtensiveModel`：全部训练场景的内生储备金扩展模型。
- `RecourseModel`：固定第一阶段决策下的独立单场景精确补救 LP。
- `StandardCCG`：串行完整场景 oracle 的标准有限场景 C&CG。

阶段3的逐场景应急采购、缺货、浪费、库存和成本均来自独立补救模型，不使用扩展模型内部非最坏场景的任意可行变量值。

## 环境

推荐 Python 3.12、Pyomo 和 HiGHS：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

检查优化器：

```powershell
python -m src.environment_check --smoke-test
```

求解器优先顺序由配置控制，默认先尝试 Gurobi，再使用开源 HiGHS。

## 测试

```powershell
python -m compileall -q src tests
python -m pytest -q
```

测试覆盖：

- 预算、供应、需求、库龄流转、到期浪费和期末容量；
- 零储备金和保质期为1的边界情形；
- 可手工核对的补救目标；
- 扩展模型目标与精确逐场景评价的一致性；
- 标准 C&CG 与全部场景扩展模型的一致性；
- 不可行补救场景的识别和加入；
- C&CG 场景去重、有限迭代和固定随机种子复现。

## 运行阶段3/4

```powershell
python -m src.run_phase3 --config configs/phase3.yaml --output outputs
```

输出：

```text
outputs/
  logs/phase3/ccg_iterations.csv
  reproducibility/phase3/manifest.json
  reproducibility/phase3/resolved_config.json
  reproducibility/phase3/training_scenarios.csv
  solutions/phase3/ccg_solution.json
  solutions/phase3/extensive_solution.json
  tables/phase3/model_comparison.csv
  tables/phase3/scenario_evaluation.csv
```

这些结果文件记录配置路径、随机种子、求解器、运行时间、上下界、迭代场景、最优储备金、储备比例和精确逐场景补救成本。正式入口还保存解析后的完整配置、完整训练场景、SHA-256 哈希、Python/依赖/求解器版本和 Git commit SHA；只有扩展式与 C&CG 均成功且目标在容差内一致时进程才以退出码 0 结束。

## 运行阶段5

```powershell
python -m src.run_phase5 --config configs/phase5.yaml --output outputs
```

阶段5输出逐预算冷/热目标、迭代次数、主问题时间、oracle 时间、初始/最终场景池以及活跃和历史对抗场景。热启动仍使用完整场景 oracle，因此不是场景删减或近似算法。配置加载或数据生成失败时会写出最小诊断；预算验证、场景池构造、冷/热求解、目标比较和状态传递失败时会保留此前已完成预算及当前失败结果，并由命令行返回非零状态。

## 阶段6实验矩阵

阶段6正式运行前先审查并冻结 `configs/phase6_experiment_matrix.yaml`。矩阵规定规模档位、三层时限、训练/测试种子、归一化预算、模型与算法对照、独立样本外评价、敏感性参数、簇统计方案、逐级扩展门槛和失败保留规则。完整说明见 `docs/phase6_experiment_matrix.md`。当前状态为待复审冻结候选，不实现或执行阶段6正式实验。

## 目录

```text
configs/
  base.yaml
  phase3.yaml
  phase5.yaml
  phase6_experiment_matrix.yaml
docs/
  mathematical_model.md
  phase3_model_and_algorithm.md
  phase5_spw_ccg.md
  phase6_experiment_matrix.md
  handoffs/
src/
  model_common.py
  model_data.py
  scenario_generator.py
  inventory_model.py
  recourse_model.py
  extensive_model.py
  evaluation.py
  ccg.py
  spw_ccg.py
  run_phase3.py
  run_phase5.py
tests/
outputs/
```

## 建模口径

- 内生储备模型使用 `regular_cost + R = B`，使储备比例可识别。
- `R` 是可用应急预算上限，不是已经发生的成本。
- 最后可用库龄满足 `available = consume + waste`，其期末库存固定为0。
- 仓储容量只计算消费和到期处置后仍可结转的期末库存。
- 连续 LP 不用 Big-M 强制严格 FIFO；在非负浪费成本下至少存在 FIFO 最优解，但退化解的具体库龄消费顺序不解释为唯一政策。
- C&CG 的 `LB` 来自受限主问题，`UB` 来自当前第一阶段解在完整场景集合上的精确评价。

阶段3模型与阶段4标准 C&CG 见 `docs/phase3_model_and_algorithm.md`，阶段5算法与公平比较口径见 `docs/phase5_spw_ccg.md`。
