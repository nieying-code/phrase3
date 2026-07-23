# 固定预算下易腐救灾物资两阶段鲁棒采购

本项目研究固定总预算在灾前常规采购与灾后应急储备之间的内生分配，并考虑多期库龄、到期浪费、仓储容量、需求波动、应急价格上涨和供应受限。

当前完成阶段3：独立精确补救模型、全部训练场景内生储备金扩展模型、完整有限场景 oracle、标准有限场景 C&CG，以及确定性/固定比例/内生模型的统一精确评价。跨预算场景池热启动 SPW-C&CG 留到阶段4。

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

## 运行阶段3

```powershell
python -m src.run_phase3 --config configs/phase3.yaml --output outputs
```

输出：

```text
outputs/
  logs/phase3/ccg_iterations.csv
  solutions/phase3/ccg_solution.json
  solutions/phase3/extensive_solution.json
  tables/phase3/model_comparison.csv
  tables/phase3/scenario_evaluation.csv
```

这些结果文件记录配置路径、随机种子、求解器、运行时间、上下界、迭代场景、最优储备金、储备比例和精确逐场景补救成本。

## 目录

```text
configs/
  base.yaml
  phase3.yaml
docs/
  mathematical_model.md
  phase3_model_and_algorithm.md
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
  run_phase3.py
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

详细数学与算法说明见 `docs/phase3_model_and_algorithm.md`。
