# Phase 3 Standard C&CG Handoff

> 阶段编号更正：本 PR 实际同时完成原计划阶段3（全场景内生储备扩展式）和阶段4（标准 C&CG）；SPW-C&CG 对应原计划阶段5。保留本文件名仅用于历史追踪。

## 任务目标

完成有限训练场景下的内生应急储备金鲁棒模型、固定第一阶段决策的独立精确补救模型、完整场景 oracle 和标准有限场景 C&CG。阶段3同时修正阶段2的评价问题：扩展模型求得第一阶段决策后，所有逐场景报告均由独立补救模型重新求解，不读取扩展模型内部的非最坏场景变量。

## 分支和提交

- Branch: `feature/phase3-standard-ccg`
- Base branch: `main`
- Initial implementation SHA: `d5b91d545b1d6cb2f3ed128c15ad2d857a139795`
- ChatGPT review-fix SHA: `4d5835448d7d979b2e55f841df5e7f141e4f2f66`
- PR链接: https://github.com/nieying-code/phrase3/pull/1
- 正式仓库: `nieying-code/phrase3`

## 修改内容

### 模型

- 新增公共库龄库存与补救约束构造器，供确定性、固定比例、内生扩展模型和 C&CG 主问题复用。
- 新增固定 \(y,R\) 的独立单场景补救模型。
- 新增场景子集受限主问题和全部训练场景内生扩展模型。
- 统一区分 `optimal`、`infeasible`、`time_limit`、`solver_error` 和 `unknown`。

### 算法

- 实现标准有限场景 C&CG。
- 初始场景由均值邻近、最高总需求、最高平均应急价格和最低总应急供应四类代表场景去重组成。
- 完整 oracle 对所有候选场景逐一独立求解；补救不可行场景优先加入。
- 每次只加入一个未重复场景，并设置有限最大迭代次数。
- 使用受限主问题目标作为 LB，完整 oracle 的精确鲁棒目标作为候选 UB。

### 测试

- 新增独立补救模型的预算、需求、库龄、到期、零储备金和保质期1测试。
- 新增人工可核对补救目标测试。
- 新增扩展模型与独立精确补救评价一致性测试。
- 新增内生模型不劣于测试固定比例最优值的测试。
- 新增 C&CG 与全场景模型目标、唯一第一阶段解、场景去重、有限迭代、不可行场景识别和随机种子复现测试。
- 保留并通过阶段1、阶段2全部原有测试。

### 配置、运行与CI

- 新增 `configs/phase3.yaml`、`src/run_phase3.py` 和阶段3标准结果文件。
- 新增 GitHub Actions Python 3.12 CI。
- 更新 README 和阶段3数学模型、算法说明。

## 关键数学和实现决策

- **内生预算规则**：`regular_cost + R = B`。未用于常规采购的预算全部定义为应急可用额度。
- **储备金含义**：\(R\) 是应急支出上限，不是真实成本；目标只计实际应急采购成本 `p*q`。
- **过期库存时点**：最后库龄满足 `available = consume + waste`，其期末库存固定为0。
- **仓储容量时点**：容量只计算消费和到期处置后仍可结转的期末库存。
- **非最坏场景重新评价**：扩展模型求出 \(y,R\) 后，全部场景均通过独立补救 LP 重新求解。
- **补救不可行处理**：C&CG 优先加入一个尚未进入主问题的不可行场景；超时和求解失败不等同于不可行。
- **上下界定义**：受限主问题目标为 LB；完整 oracle 对当前第一阶段解得到的真实鲁棒目标为候选 UB；历史最小候选 UB 为全局 UB。
- **终止条件**：仅当全部场景补救达到最优可行时检查
  `UB - LB <= abs_tol + rel_tol * max(1, abs(UB))`。
- **一致性保护**：若最坏场景已在主问题而 gap 仍不收敛，则返回一致性错误，不强行声明最优。

## 修改文件

- `src/model_common.py`：公共模型构造器、求解器选择和状态归一化。
- `src/inventory_model.py`：确定性和固定储备模型兼容接口。
- `src/recourse_model.py`：独立单场景精确补救模型。
- `src/extensive_model.py`：受限主问题和全部场景扩展模型。
- `src/evaluation.py`：全部场景独立精确评价。
- `src/ccg.py`：标准有限场景 C&CG。
- `src/run_phase3.py`：阶段3统一运行与结果输出。
- `configs/phase3.yaml`：阶段3配置。
- `tests/test_recourse_model.py`：补救模型测试。
- `tests/test_extensive_model.py`：扩展模型测试。
- `tests/test_ccg.py`：C&CG测试。
- `docs/phase3_model_and_algorithm.md`：数学模型和算法说明。
- `.github/workflows/ci.yml`：Python 3.12 CI。
- `outputs/logs/phase3/ccg_iterations.csv`：C&CG迭代日志。
- `outputs/solutions/phase3/*.json`：扩展模型与C&CG解。
- `outputs/tables/phase3/*.csv`：模型比较和逐场景评价。

## 验证结果

实际执行：

```text
python -c "import pyomo, highspy; ... SolverFactory('appsi_highs').available(...)"
```

结果：Pyomo `6.10.1`；HiGHS 可用；实际求解器为 `appsi_highs`。

```text
python -m compileall -q src tests
```

结果：退出码0，语法检查通过。

```text
python -m pytest -q
```

结果：`22 passed in 2.71s`。

```text
python -m src.run_phase3 --config configs/phase3.yaml --output outputs
```

结果：

- 全场景扩展模型状态：`optimal`
- 全场景扩展模型目标：`3269.9644075814263`
- 标准 C&CG 状态：`optimal`
- 标准 C&CG 目标：`3269.9644075814263`
- 两者绝对差值：`0.0`
- C&CG LB：`3269.9644075814276`
- C&CG UB：`3269.9644075814263`
- 浮点 gap：`-1.3642420526593924e-12`（数值舍入量级，等价于0）
- C&CG迭代次数：`5`
- 最终主问题场景数：`7`
- 最坏场景：`s0016`
- 最优储备金：`0.0`
- 储备比例：`0.0`
- 随机种子：`20260723`
- CI状态：`success`（GitHub Actions `ci`，run #9，验证审查修复提交 `4d58354`）

## ChatGPT审查修复

- **P1 限时与不可行状态**：所有求解均使用
  `load_solutions=False`，先读取求解器终止条件；仅在终止状态为最优时加载解。
  `NoFeasibleSolutionError` 等异常不再根据异常类型或文本猜测为不可行，而是归为
  `solver_error`。新增真实 HiGHS 不可行模型、模拟限时终止和异常路径测试。
- **P2 求解器容差配置**：`feasibility_tolerance` 与
  `optimality_tolerance` 已从配置贯穿确定性模型、固定比例模型、扩展模型、独立
  recourse oracle 和 C&CG。HiGHS 映射到 primal/mip/dual feasibility
  tolerance，Gurobi 映射到 `FeasibilityTol` 与 `OptimalityTol`。结果JSON记录实际
  配置值。
- **P3 handoff元数据**：已更新初始提交、审查修复提交、PR链接、测试数量和最新
  已验证CI。
- 修复后正式实例目标仍为 `3269.9644075814263`，与修复前一致；C&CG仍在5次
  迭代收敛，最优储备金仍为 `0.0`。

## 已知限制

- 未实现 SPW-C&CG 和跨预算场景池热启动；按原始计划留待阶段5。
- oracle 当前为串行枚举，未并行化。
- 未实现严格二进制 FIFO；当前线性模型保证存在 FIFO 最优解。
- 仓储容量采用到期处置后的期末口径，不限制到货瞬间临时占用。
- 未实现配送路径、机器学习、分布鲁棒优化和连续预算不确定集。
- 当前 Codex 沙箱只允许在 C 盘工作区写入，无法直接把本地副本写入用户指定的 D 盘；正式协作副本位于 GitHub，D盘参考项目保持未修改。

## 风险点

- `src/model_common.py` 中库龄流转、最后库龄浪费和容量约束。
- Pyomo/HiGHS 终止状态及异常归一化。
- `src/extensive_model.py` 的主问题目标与独立补救一致性判定。
- `src/ccg.py` 的全局上下界更新、不可行场景和重复最坏场景保护。
- 阶段2固定比例预算不等式与阶段3内生预算等式的政策差异。
- 本实例得到 \(R=0\)，审查时应确认这是数据驱动结果而非储备金约束遗漏。

## 下一步建议

阶段5实现跨预算场景池热启动 SPW-C&CG：保存前一预算的最终场景集、历史最坏场景和活跃场景；对每个预算同时运行冷启动与热启动；验证目标一致性，并分别记录迭代次数、主问题时间和 oracle 时间。

## ChatGPT审查清单

1. 库龄和到期流转是否守恒；
2. \(R\) 是否只表示可用预算而非真实成本；
3. 非最坏场景是否使用独立补救模型；
4. LB 和 UB 方向是否正确；
5. 补救不可行场景处理是否正确；
6. C&CG 是否可能重复加场景或错误终止；
7. 全场景模型与 C&CG 是否真正使用同一组约束；
8. 测试是否覆盖模型关键性质；
9. 是否存在数值容差或结果提取问题；
10. 是否有未记录的假设变化。
