# Phase 4 SPW-C&CG Handoff

## 任务目标

在阶段3标准有限场景 C&CG 的基础上，实现严格递增预算序列之间的场景池热启动 SPW-C&CG。每个预算同时运行冷启动和热启动算法，完整精确 oracle 始终扫描全部候选场景，并把冷/热目标一致作为阶段4正确性门槛。

## 分支、提交与 PR

- Branch: `agent/phase4-spw-ccg`
- Base branch: `main`
- Base merge SHA: `dee5eac1b5b13b843f3dfc98df71bbff3fed377f`
- Original Phase 4 implementation SHA: `a528cb020ed6a5e666cb28be3ce451b15f818ace`
- Published review remediation code SHA: `04dfff10d3fcbe35a24b31373f6f7865dc5f3d9d`
- Equivalent locally validated Git commit: `1a28d0247dcad3a846c35d19b09cb156a396dfba`
- 最终远程 PR head：以 PR 页面显示为准；handoff 文档提交晚于上述代码提交，避免把旧实现 SHA 误写成最终代码版本。
- PR（Ready for review）: https://github.com/nieying-code/phrase3/pull/2
- Repository: `nieying-code/phrase3`

## 实现内容

### SPW-C&CG

- 新增 `src/spw_ccg.py`。
- 对每个预算分别运行冷启动标准 C&CG 与场景池热启动 C&CG。
- 下一预算的热启动池采用：

  ```text
  base scenarios
  + previous active scenarios
  + cumulative historical adversarial scenarios
  ```

- 活跃场景由最终第一阶段解的完整精确补救成本识别：与最坏补救成本之差不超过 `active_scenario_tolerance`。
- 历史对抗池累积保存热启动迭代中加入过的不可行/最坏场景以及各预算最终最坏场景。
- 保存每个预算的最终主问题场景集用于诊断，但不无条件把整个最终集合复制到下一预算。
- 所有集合按原始场景顺序去重，保证结果可复现。
- 完整 oracle 没有裁剪，因此热启动只改变初始受限主问题，不改变鲁棒问题。

### 正确性和公平比较

- 预算必须严格递增。
- 冷、热算法必须都达到 `optimal`。
- 冷、热目标按绝对加相对容差进行一致性检查；任一预算超差时阶段4状态变为 `inconsistent_cold_warm_objectives`。
- 相邻预算交替使用 `cold->warm` 与 `warm->cold` 运行顺序。
- 冷、热总时间均计入各自场景池构造时间。
- 分别记录主问题时间、oracle 时间、总时间、迭代数、初始池和最终池规模。

### 运行与交付

- 新增 `configs/phase4.yaml`。
- 新增 `src/run_phase4.py`。
- 新增 `docs/phase4_spw_ccg.md`。
- 更新 README 与 `.gitignore`。
- 新增：
  - `outputs/solutions/phase4/spw_ccg_results.json`
  - `outputs/tables/phase4/budget_comparison.csv`
  - `outputs/tables/phase4/scenario_pool_transfer.csv`
  - `outputs/logs/phase4/ccg_iterations.csv`

## 测试

执行：

```text
python -m compileall -q src tests
python -m pytest -q
```

结果：

- 语法检查通过。
- 审查整改前本地结果：`25 passed in 7.23s`。
- 审查整改后本地完整回归：`27 passed in 17.24s`。
- 按 CI 步骤拆分复核：`26 passed in 5.64s`，阶段4端到端测试 `1 passed in 10.19s`。

新增测试覆盖：

- 多预算下冷、热算法目标一致；
- 冷、热均保持完整场景可行性并正常收敛；
- 三个连续预算中，热池独立验证为基础场景、上一预算活跃场景与累积历史对抗场景的去重并集；
- 历史对抗场景跨预算单调累积，并独立核对其来源；
- 活跃场景按完整精确补救成本和容差公式独立核对；
- 活跃和历史集合不会出现候选集外场景；
- 每次冷、热求解的精确场景成本均覆盖全部候选场景；
- 冷、热目标超差时阶段状态不能错误报告为 `optimal`；
- 冷/热执行顺序按预算交替；
- 非递增预算序列被拒绝；
- 正式六预算入口生成完整 JSON、对比表、场景池传递表和迭代日志。

## 审查整改

针对 PR #2 的阶段4复核意见，本次追加：

1. CI 将普通回归与正式阶段4端到端验证分成两个明确步骤；
2. 新增 `tests/test_run_phase4.py`，直接执行 `configs/phase4.yaml` 的六预算配置并检查四类交付文件；
3. 场景池测试不再调用生产辅助函数计算期望集合，改为按数学定义独立构造；
4. 跨三个预算检查历史场景的累积性、活跃场景定义和完整 oracle 覆盖；
5. 命令行入口在阶段状态不是 `optimal` 时返回失败，使 CI 能拦截冷、热目标不一致等异常。

CI：

- 整改前基线：[run #15](https://github.com/nieying-code/phrase3/actions/runs/30027365666)，成功，`25 passed in 7.73s`。
- 整改代码提交：[run #16](https://github.com/nieying-code/phrase3/actions/runs/30062424940)，成功。
  - 普通回归：`26 passed in 3.71s`；
  - 阶段4正式端到端验证：`1 passed in 5.63s`。

## 正式小规模验证

运行：

```text
python -m src.run_phase4 --config configs/phase4.yaml --output outputs
```

环境：

- Python 3.12
- Pyomo 6.10.1
- HiGHS / `appsi_highs`
- 随机种子 `20260723`
- 1种物资、4期、20个训练场景

结果：

| 预算 | 鲁棒目标 | 冷迭代 | 热迭代 | 减少 | 冷初始池 | 热初始池 | 最优储备金 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 700 | 9689.611544 | 1 | 1 | 0 | 3 | 3 | 0 |
| 800 | 7523.229281 | 4 | 4 | 0 | 3 | 3 | 0 |
| 900 | 5381.392979 | 5 | 2 | 3 | 3 | 6 | 0 |
| 1000 | 3269.964408 | 5 | 1 | 4 | 3 | 7 | 0 |
| 1100 | 1184.249769 | 4 | 2 | 2 | 3 | 7 | 0 |
| 1200 | 1115.180981 | 6 | 2 | 4 | 3 | 8 | 149.044650 |

- 所有预算冷、热目标差：`0.0`。
- 冷启动总迭代数：`25`。
- 热启动总迭代数：`12`。
- 总迭代减少：`13`。
- 本次冷启动总时间：约 `4.97s`。
- 本次热启动总时间：约 `2.40s`。

时间来自单随机种子、小规模、单次运行，只能作为正确性和可运行性证据，不能单独支持统计意义上的加速结论。

## 关键解释

- 700预算时基础池已经包含最终最坏场景，因此冷、热都在1次迭代结束。
- 800预算时上一预算只传递了已在基础池内的最坏场景，热池没有扩大，所以没有减少迭代。
- 从900预算开始，历史不可行/最坏场景进入热池，迭代数明显下降。
- 1200预算时最优储备金变为 `149.044650`，说明阶段3的 `R=0` 是特定预算和数据下的结果，不是模型遗漏储备金作用。

## 已知限制

- 当前只完成单种子、小规模正确性实验。
- 尚未按正式论文口径运行多随机种子、重复计时、中位数与四分位区间。
- oracle 仍为串行枚举。
- 没有实现变量 warm start。
- 历史对抗池暂不裁剪；大量预算和场景下可能导致初始主问题过大。
- 未实现严格二进制 FIFO、路径、机器学习、连续预算不确定集和分布鲁棒优化。

## ChatGPT 审查重点

1. 热池是否严格由基础、上一预算活跃和累积历史对抗场景构成；
2. 活跃场景定义是否与最终精确补救成本一致；
3. 完整 oracle 是否始终保留；
4. 冷、热目标一致性判定是否正确；
5. 历史对抗场景是否完整、去重且顺序稳定；
6. 交替运行顺序与场景池构造时间是否真正进入公平比较；
7. 小规模结果是否存在过度解读；
8. 测试是否覆盖跨预算传递的关键性质。

## 下一步建议

PR通过审查并合并后，下一阶段优先扩展正式实验：

1. 使用至少3个随机种子，时间允许时每组重复5至10次；
2. 报告冷/热迭代数和运行时间的中位数、四分位区间；
3. 研究预算步长对关键场景稳定性和加速效果的影响；
4. 增加活跃场景 Jaccard 相似度、场景复用率与加速比；
5. 当历史池过大时，再比较不裁剪与受控裁剪策略，但完整 oracle 始终保留。
