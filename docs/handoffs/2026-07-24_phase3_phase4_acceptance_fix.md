# Phase 3/4 Engineering Acceptance Fix Handoff

## 任务目标

在不回滚 PR #1、也不改写既有 Git 历史的前提下，补齐原计划阶段3（全场景内生储备扩展式）和阶段4（标准 C&CG）的工程验收闭环：正式运行自动判定成功或失败、求解器边界状态明确分类、生成器形式参数可重复使用、结果具备可复现输入与环境快照，并统一阶段编号和 FIFO 文档表述。

## 分支、提交与 PR

- Branch: `fix/phase3-phase4-acceptance`
- Base branch: `main`
- Base SHA: `dee5eac1b5b13b843f3dfc98df71bbff3fed377f`
- Remote code and tests commit: `70ee2a06b16bb71b88617b532f56521abbb14686`
- Remote documentation commit: `721b0fa27936e6b80768d69e412852473ccbec62`
- Remote artifact line-ending commit: `28718083e7be855d2b5f4cee280ee72d179468f5`
- Remote reproducibility snapshot commit: `f004b474cf3ad21e98c763f579b517afc6ea7fd5`
- Pre-handoff-update remote head: `095c09090ce30317bec7f102933c387a93d0e60e`
- Final remote head: 以 PR 页面为准；本 handoff 更新是最后一项文档变更。
- PR: https://github.com/nieying-code/phrase3/pull/3

## 修改内容

### 正式运行验收

- `run_phase3.run()` 对扩展式状态、C&CG 收敛、C&CG 终止状态、目标可用性和扩展式/C&CG 目标一致性执行五项强制检查。
- 验收结果写入顶层返回值、扩展式 JSON、C&CG JSON 和可复现 manifest。
- `main()` 在任何验收项失败时打印诊断后以非零状态退出，CI 不再把 `oracle_failure`、超时、最大迭代或目标不一致误判为成功。
- 新增正式配置端到端测试和模拟 `oracle_failure` 的非零退出测试。

### Iterable 参数

- `run_standard_ccg()`、`evaluate_first_stage()` 和 `solve_endogenous_extensive()` 在入口立即把 `solver_preference` 固化为非空元组。
- 新增生成器形式 `solver_preference=(name for name in ("highs",))` 的直接接口测试。

### 求解器状态

- `unbounded` 归一化为 `status="unbounded"`。
- `infeasibleOrUnbounded` 归一化为 `status="infeasible_or_unbounded"`。
- 两种状态均有回归测试，不再落入 `solver_error` 或 `unknown`。

### 可复现输出

正式入口新增：

- `outputs/reproducibility/phase3/resolved_config.json`：解析后的完整配置；
- `outputs/reproducibility/phase3/training_scenarios.csv`：实际训练场景的需求、应急价格和应急供应；
- `outputs/reproducibility/phase3/manifest.json`：配置/场景 SHA-256、场景生成器版本、Python/平台、依赖包、求解器版本、Git commit SHA、工作树状态、实际报告求解器和正式验收结果。

源代码和运行环境信息在创建输出文件前捕获，避免把本次运行刚写出的结果误判为运行前已有的工作树修改。

### 文档一致性

- 明确 PR #1 实际同时完成原计划阶段3和阶段4，SPW-C&CG 对应阶段5。
- 保留历史文件名和提交历史，仅补充编号更正说明。
- 将“已经使用词典序破平局实现 FIFO”纠正为：当前只保证至少存在 FIFO 最优解，尚未执行第二级词典序破平局，也不保证求解器返回严格 FIFO 解。

## 关键实现决策

- 正式验收使用 `phase3.consistency_tolerance` 对扩展式和 C&CG 精确目标的绝对差进行检查。
- 只有 `extensive.status == "optimal"`、`ccg.converged == True`、`ccg.termination_status == "optimal"`、两目标均为有限值且差值不超过容差时，正式运行才通过。
- `infeasible`、`unbounded`、`infeasible_or_unbounded`、`time_limit`、`solver_error` 和 `unknown` 保持不同语义。
- 求解失败不被解释为不可行；C&CG oracle 失败不会被允许进入成功退出路径。
- 场景 CSV 与解析配置分别保存并独立哈希；manifest 同时记录代码和运行环境。

## 主要修改文件

- `src/run_phase3.py`：正式验收门槛、非零退出与可复现输出。
- `src/reproducibility.py`：哈希、Python/依赖/求解器/Git 元数据。
- `src/model_common.py`：无界及不可行或无界状态分类。
- `src/ccg.py`、`src/evaluation.py`、`src/extensive_model.py`：可重复使用的求解器偏好。
- `tests/test_run_phase3.py`：正式入口成功和失败门槛。
- `tests/test_solver_status.py`：边界状态测试。
- `tests/test_ccg.py`、`tests/test_extensive_model.py`：生成器参数测试。
- `README.md`、`docs/project_plan.md`、`docs/phase3_model_and_algorithm.md`、`docs/phase1_completion_report.md`、`docs/research_design.md`：阶段编号、运行验收、复现性与 FIFO 表述。

## 验证结果

执行：

```text
python -m compileall -q src tests
python -m pytest -q
python -m src.run_phase3 --config configs/phase3.yaml --output D:\新建文件夹\项目交付\阶段3-4修复\验证输出
```

结果：

- 语法检查：通过。
- 针对性测试：`14 passed in 7.27s`。
- 完整回归：`28 passed in 11.71s`（最终提交前复核；此前同一测试集为 `28 passed in 6.46s`）。
- 正式验收状态：`passed`。
- 扩展式目标：`3269.9644075814263`。
- C&CG 目标：`3269.9644075814263`。
- 目标差：`0.0`，验收容差 `1.0e-5`。
- C&CG 迭代：`5`。
- 最坏场景：`s0016`。
- 最优储备金：`0.0`，储备比例 `0.0`。
- 求解器：HiGHS / `appsi_highs`。
- 配置 SHA-256：`22ca2be7ce1c9afdb9ef7807cbf029c9ee21eaeb07ba7ed45de05b13c968d6b3`。
- 场景 SHA-256：`b17f4274e38cfccdebed6685c4122820f6c679f61db62e94aed16d07144d3b90`。
- 可复现快照记录的代码 SHA：`d0e55f2eb93e948b163fc5a96ac848c933a51efa`，运行前工作树为干净状态。
- CI：[run #22](https://github.com/nieying-code/phrase3/actions/runs/30068490961)，成功；语法检查通过，`28 passed in 8.02s`。

## PR #2 合并后同步

- PR #2 已合并到 `main`，合并提交为 `ebf347162fdf8962bf901fa7a8170385ed91ecc0`。
- PR #3 已通过非强制 merge 同步最新 `main`，没有改写既有远程提交历史。
- 合并冲突仅涉及 `README.md`、旧阶段3 handoff 和 `tests/test_extensive_model.py`：
  - README 同时保留阶段3/4历史映射和阶段5已完成状态；
  - 旧 handoff 改为“PR #1 当时未实现、后来由 PR #2 完成阶段5”的历史表述；
  - 生成器参数测试保留 PR #2 中拆分更细的两个独立接口测试。
- 同步后本地完整回归：`41 passed in 26.70s`。
- 按当前 CI 步骤拆分复核：普通回归 `35 passed in 13.80s`，阶段5端到端及失败诊断 `6 passed in 16.91s`。
- 同步后 CI：pending。

## 已知限制

- 当前 oracle 仍为串行枚举。
- 当前只保证存在 FIFO 最优解，未实现词典序二级求解或严格二进制 FIFO。
- 仓储容量采用到期处置后的期末口径，不限制到货瞬间临时占用。
- 未实现配送路径、机器学习、连续不确定集和分布鲁棒优化。
- 正式实例仍是单种子小规模正确性验证，不构成统计性能结论。

## 风险点

- `src/run_phase3.py` 的成功判定是否覆盖所有失败终止状态；
- `src/model_common.py` 对不同 Pyomo/求解器终止条件的跨后端一致性；
- manifest 中 Git 状态是否确实在输出写入前捕获；
- 阶段5 PR 合并后，重复的 Iterable 修复是否能无冲突保留；
- FIFO 更正文档是否仍有遗漏的旧表述。

## 下一步建议

1. ChatGPT 通过修复 PR 复核正式验收门槛、边界状态和复现 manifest；
2. 合并后重新运行阶段3/4正式配置，使用合并提交生成归档结果；
3. 阶段5 PR 若晚于本 PR 合并，确认其基线更新后仍通过全部测试；
4. 正式论文实验阶段再扩展多种子、重复计时和样本外评价。

## ChatGPT 审查清单

1. C&CG 不收敛、oracle 失败、超时或最大迭代是否必然导致非零退出；
2. 扩展式与 C&CG 目标不一致是否必然阻断正式验收；
3. 生成器形式的 `solver_preference` 是否在所有多次使用入口安全；
4. `unbounded` 和 `infeasibleOrUnbounded` 是否分类正确；
5. 配置、场景、哈希、版本和 Git SHA 是否完整且相互可核验；
6. 场景 CSV 是否覆盖所有训练场景、物资和时期；
7. PR #1 的阶段3/4映射和阶段5定义是否清楚；
8. FIFO 文档是否不再声称已实现不存在的词典序求解；
9. 新测试是否真正进入 GitHub Actions；
10. 是否引入与阶段5 PR 的不必要耦合。
