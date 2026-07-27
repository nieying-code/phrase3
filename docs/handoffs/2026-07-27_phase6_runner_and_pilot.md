# Phase 6 Runner and Pilot Handoff

## 任务目标

把已审查的阶段6实验矩阵变成可执行、可恢复、可诊断的实验基础设施，并且只运行
开发种子和试运行种子。在完整试运行计算量门槛和矩阵正式状态门槛通过前，禁止
正式种子。

## 分支和提交

- Branch: `agent/phase6-experiment-runner`
- Base branch: `main`
- Base commit: `93f042a3673519ecd29130db0bd37dbd1e6c6cba`
- Validated implementation snapshot: `f6746c70590398bbc094d157267369b05ea3718e`
- PR: https://github.com/nieying-code/phrase3/pull/5
- PR mode: Draft
- CI: Actions run
  [30264431046](https://github.com/nieying-code/phrase3/actions/runs/30264431046)
  succeeded on head `127b8b7bae0df6af2d77bfdee80a3fe539d1fa27`

## 修改内容

### 生成器

- 新增 `src/phase6_protocol.py`，严格解析矩阵 v1.3 和受控生成协议 v1.0。
- 固定 NumPy `2.5.1`、PCG64DXSM、抽取顺序、相关变换和截断规则。
- 自动重算 D0–P4 参考预算并校验矩阵缓存值。
- 将 development、pilot、formal 三类种子隔离；候选矩阵下正式种子被拒绝。

### 运行器

- 新增 `src/phase6_worker.py`、`src/phase6_runner.py` 和 `src/run_phase6.py`。
- 每个算法—预算—技术重复使用独立工作进程。
- 分别执行求解器调用时限、单预算墙钟时限和六预算序列墙钟时限。
- 看门狗超时会终止工作进程树，避免遗留求解器进程。
- 冷/热顺序按预算交替，技术重复先取中位数。
- 冷/热目标不一致、非最优、超时或状态传递失败均阻断后续预算。
- 每个完成预算配对后原子 checkpoint，恢复时强制校验运行指纹。
- 同一 run 的重试 worker 文件带 attempt 编号，不覆盖旧诊断。

### 输出和可复现性

- 新增全局 run registry、failure registry 和逐重复性能表。
- 保存解析运行、训练场景、迭代日志、预算比较和 manifest。
- Manifest 包含文件哈希、Git、Python、依赖、求解器、单线程、CPU 和内存信息。
- 新增保守试运行投影；只有 V1/V2/P1/P2 × 三个试运行种子全部存在时才评估
  720 小时总门槛和 336 小时单实验族门槛。
- 原始实验输出放在 D 盘并由 `.gitignore` 排除。

### 求解器控制

- `solve_with_status()` 及 C&CG、扩展式、补救和 SPW-C&CG 调用链新增
  `solver_threads` 参数。
- HiGHS 设置 `threads`，Gurobi 设置 `Threads`。
- 非正线程数作为无效求解器选项返回。

### 测试

- 新增协议完整性、参考预算、确定性、D0历史口径和正式种子门槛测试。
- 新增运行器交替顺序、技术重复、checkpoint、registry、失败恢复和继续执行测试。

## 关键实现决策

- 正式种子使用双重门槛：矩阵状态必须是
  `frozen_for_formal_execution`，完整试运行投影还必须通过。
- 求解器调用时限不等于算法墙钟时限；墙钟限制由父进程实施。
- 六预算限时分别作用于每个冷/热算法及每个技术重复。
- 只有完整、最优且通过冷/热目标一致性检查的预算才写入
  `comparisons` 并用于状态传递。
- 状态传递使用上一个最优热启动结果的活跃场景和累积对抗场景；
  oracle 仍评价完整训练场景。
- 技术重复仅用于计时稳定性，不作为独立统计样本。
- 当前吞吐信息只用于描述 V1；缺少 V2/P1/P2 时不计算正式总工时结论。

## 修改文件

- `configs/phase6_runner.yaml`：runner 与求解器执行配置。
- `src/phase6_protocol.py`：冻结矩阵解析和受控生成器。
- `src/phase6_worker.py`：单个 C&CG 工作进程。
- `src/phase6_runner.py`：配对运行、三层时限、checkpoint、恢复和注册。
- `src/phase6_reporting.py`：逐重复性能表和试运行覆盖/工时投影。
- `src/run_phase6.py`：命令行入口和顶层失败诊断。
- `src/model_common.py` 等：单线程求解器参数贯通。
- `src/reproducibility.py`：`psutil`、硬件和线程元数据。
- `tests/test_phase6_protocol.py`、`tests/test_phase6_runner.py`：专项测试。
- `docs/phase6_runner_and_pilot.md`：运行协议和当前边界。

## 验证结果

实际执行：

- `python -m compileall -q src tests`：通过。
- `python -m pytest -q`：`56 passed in 28.50s`。
- `git diff --check`：通过；仅显示 Windows 工作树 LF/CRLF 转换提示。
- 候选矩阵下用正式种子调用 `--mode formal`：写出
  `runner_exception.json`，失败阶段为 `phase6_sequence`，进程退出码为 `1`。
- GitHub Actions run `30264431046`：普通回归 `50 passed in 18.82s`，
  Phase 5 端到端 `6 passed in 11.86s`。

D0 开发回归：

```powershell
python -m src.run_phase6 --config configs/phase6_runner.yaml `
  --output outputs --tier D0 --seed 20260723 --mode development `
  --run-id dev_d0_phase6_impl_v2
```

- 状态：`optimal`
- 完成预算：`6/6`
- 预算 1000 冷/热目标：`3269.9644075814263`
- 冷/热目标差：`0`
- 求解器：`appsi_highs 1.15.1`

V1 试运行：

```powershell
python -m src.run_phase6 --config configs/phase6_runner.yaml `
  --output outputs --tier V1 --seed <pilot-seed> --mode pilot `
  --run-id pilot_v1_<pilot-seed>
```

三个种子 `2026072001/2026072002/2026072003` 均为 `optimal`，共完成
`18/18` 个预算配对和 `108/108` 次算法执行。最大冷/热目标差为
`1.8189894035458565e-12`。代表运行的冷启动迭代总数分别为
`59/44/55`，热启动为 `16/12/14`。

当前 V1 三种子的中位观测速率：

- 主问题求解：`3946.085 次/小时`
- 补救 LP：`197304.233 次/小时`
- 算法执行：`686.276 次/小时`
- 完成预算配对：`114.379 对/小时`
- 峰值内存：`77.586 MB`

试运行投影状态：

- 已完成必需“档位—种子”运行：`3/12`
- 未完成：V2、P1、P2 各三个种子
- 状态：`insufficient_pilot_coverage`
- `formal_execution_authorized=false`

## 已知限制

- 当前 PR 只完成算法性能试运行 runner，不包含 E1/E2/E4/E5 的全部实验编排。
- 全局 CSV 使用原子替换但未实现多主进程并发锁；当前协议要求由一个主 runner
  串行管理运行。
- V2/P1/P2 尚未实测，V1 吞吐不能外推为正式总工时结论。
- 大规模超时进程树终止已实现，但尚未在 P2–P4 实际超时条件下验证。
- 样本外评价、bootstrap、绘图和真实数据校准留给后续任务。

## 风险点

- `src/phase6_protocol.py` 的随机抽取顺序、截断和惩罚公式。
- `src/phase6_runner.py` 的三层时限累计、失败 checkpoint 和恢复指纹。
- `src/phase6_runner.py` 的冷/热代表重复选择与状态传递时点。
- `src/phase6_reporting.py` 的 LP 调用计数和完整试运行覆盖门槛。
- Windows 下外部看门狗终止进程树和原子替换行为。

## 下一步建议

1. 先完成 V2、P1、P2 的三个试运行种子。
2. 审查完整试运行投影；若门槛失败，版本化修改矩阵，不得运行正式种子。
3. 门槛通过后，用独立 PR 将矩阵状态改为
   `frozen_for_formal_execution`。
4. 再实现 E1/E2/E4/E5 编排、样本外评价和统计汇总。
5. 最后按档位逐级启动正式种子，P3/P4 仍受前一档规模门槛控制。

## ChatGPT审查清单

1. 受控生成器是否逐字段忠实执行矩阵 v1.3。
2. PCG64DXSM、NumPy版本和随机抽取顺序是否足以复现。
3. 三层时限是否具有不同且正确的作用域。
4. 超时是否终止完整进程树并保留当前诊断。
5. checkpoint 是否只在完整配对后推进，恢复是否可能重复或跳过预算。
6. 只有最优热启动状态是否能传递，完整 oracle 是否始终保留。
7. 技术重复是否先取中位数且未被当作独立样本。
8. 冷/热目标容差和失败终止方向是否正确。
9. 全局 registry 和失败文件是否可能在并发运行时竞争。
10. 正式种子门槛是否确实无法被候选矩阵绕过。
11. 吞吐计数与完整试运行覆盖规则是否过度乐观。
12. V1结果是否被正确限定为描述性试运行而非正式结论。
