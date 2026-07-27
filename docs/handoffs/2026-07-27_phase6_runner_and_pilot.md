# Phase 6 Runner and Pilot Handoff

## 任务目标

把已审查的阶段6实验矩阵变成可执行、可恢复、可诊断的实验基础设施，并且只运行
开发种子和试运行种子。在完整试运行计算量门槛和矩阵正式状态门槛通过前，禁止
正式种子。

## 分支和提交

- Branch: `agent/phase6-experiment-runner`
- Base branch: `main`
- Base commit: `93f042a3673519ecd29130db0bd37dbd1e6c6cba`
- Review-fix implementation snapshot:
  `28340e5182affb18bd778bc9dc6420b966e71a96`
- PR: https://github.com/nieying-code/phrase3/pull/5
- PR mode: Draft
- CI: Actions run
  [30270232066](https://github.com/nieying-code/phrase3/actions/runs/30270232066)
  succeeded on review-fix head
  `c32c1bece422709c71427571626bfa568908212b`

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
- 终态失败或超时 checkpoint 不允许 `--resume`；诊断重试必须使用新
  `run_id` 和 `parent_run_id`，首次失败始终保留在完成率分母中。
- 每次 C&CG 迭代原子写入 heartbeat；外部看门狗超时后读取并保留当前
  迭代日志、LB/UB、场景池和最坏场景。

### 输出和可复现性

- 新增全局 run registry、failure registry 和逐重复性能表。
- 保存解析运行、训练场景、迭代日志、预算比较和 manifest。
- Manifest 包含文件哈希、Git、Python、依赖、求解器、单线程、CPU 和内存信息。
- 投影严格过滤科学配置、runner 配置和 E3 组件代码三类 SHA-256；原始矩阵
  文件哈希仅作追溯，不再因状态或修订日期变化使试运行失效。
- 失败主运行、诊断重试和重复主运行分开统计；成功诊断不得覆盖首次失败。
- E3 只用“补救 LP 调用数/补救 LP 每小时”的同量纲口径。E1/E2/E4/E5
  执行器未实现前统一返回 `projection_incomplete`，不生成正式授权。
- 全局 registry、性能表、失败表和投影由成熟跨平台文件锁保护；同一
  `run_id` 另有覆盖完整运行周期的排他锁。
- 原始实验输出放在 D 盘并由 `.gitignore` 排除。

### 求解器控制

- `solve_with_status()` 及 C&CG、扩展式、补救和 SPW-C&CG 调用链新增
  `solver_threads` 参数。
- HiGHS 设置 `threads`，Gurobi 设置 `Threads`。
- 非正线程数作为无效求解器选项返回。

### 测试

- 新增协议完整性、参考预算、确定性、D0历史口径和正式种子门槛测试。
- 新增正式双重门槛、投影指纹/量纲、不可变失败、诊断谱系、heartbeat
  超时保留和并发 registry 写入测试。

## PR #5 审查修复

1. 正式入口现在在场景生成前核验矩阵状态、完整投影、三类指纹、12项覆盖、
   计算门槛和显式授权。
2. 删除 E1/E2/E5 的错误“实例数/主问题每小时”估计；E1/E2/E4/E5
   执行器未完成时投影明确为 `projection_incomplete`。
3. `failed/timeout` 成为不可变终态；诊断重试使用新运行及 `parent_run_id`。
4. C&CG 每次迭代写 heartbeat，外部超时结果包含 `partial_progress`。
5. 所有全局 CSV 和投影的读取—修改—替换由跨进程锁串行化。
6. 失败序列现在为全部六个预算写入显式状态：失败预算保留实际状态，后续预算
   为 `not_run_after_pair_sequence_failure`；逐算法表同时补齐所有计划重复。
7. 正式门槛使用排除生命周期字段的科学配置哈希和显式 E3 组件哈希，矩阵状态
   切换或新增 E1/E2/E4/E5 模块不会让 E3 试运行失效。
8. 汇总锁改用 `filelock` 的跨平台 OS 锁，并用真实多进程测试验证；同一 run
   的第二个进程和活动运行期间的 `--resume` 会立即被拒绝。

## 关键实现决策

- 正式种子使用双重门槛：矩阵状态必须是
  `frozen_for_formal_execution`，完整试运行投影还必须通过。
- 求解器调用时限不等于算法墙钟时限；墙钟限制由父进程实施。
- 六预算限时分别作用于每个冷/热算法及每个技术重复。
- 六个计划预算都写入终态 `comparisons`；只有完整、最优且通过冷/热目标
  一致性检查的预算计入完成数并用于状态传递。
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
- `src/phase6_locking.py`、`requirements.txt`：跨平台文件锁和依赖。
- `src/run_phase6.py`：命令行入口和顶层失败诊断。
- `src/model_common.py` 等：单线程求解器参数贯通。
- `src/reproducibility.py`：`psutil`、硬件和线程元数据。
- `tests/test_phase6_protocol.py`、`tests/test_phase6_runner.py`、
  `tests/test_phase6_reporting.py`：专项测试和真实多进程锁验证。
- `docs/phase6_runner_and_pilot.md`：运行协议和当前边界。

## 验证结果

实际执行：

- `python -m compileall -q src tests`：通过。
- `python -m pytest -q`：`68 passed in 35.53s`。
- `git diff --check`：通过；仅显示 Windows 工作树 LF/CRLF 转换提示。
- 候选矩阵下用正式种子调用 `--mode formal`：写出
  `runner_exception.json`，失败阶段为 `phase6_sequence`，进程退出码为 `1`。
- GitHub Actions run `30270232066`：普通回归 `58 passed in 19.41s`，
  Phase 5 端到端 `6 passed in 11.89s`。

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
  --run-id pilot_v1_reviewfix_<pilot-seed>
```

三个种子 `2026072001/2026072002/2026072003` 使用 run ID
`pilot_v1_audit2_<seed>`，均为 `optimal`，共完成
`18/18` 个预算配对和 `108/108` 次算法执行。最大冷/热目标差为
`1.8189894035458565e-12`。代表运行的冷启动迭代总数分别为
`59/44/55`，热启动为 `16/12/14`。

当前 V1 三种子的中位观测速率：

- 主问题求解：`3939.795 次/小时`
- 补救 LP：`196989.736 次/小时`
- 算法执行：`687.371 次/小时`
- 完成预算配对：`114.562 对/小时`
- 峰值内存：`77.285 MB`

本轮稳定指纹：

- 原始矩阵文件 SHA-256：
  `18a2a9eb26127486c09a659225ee6c95400e1946f71314d7b723bcf9262efa80`
- 科学配置 SHA-256：
  `7d9e0df1b299fb11cff8268a01a557493bbf32e038ae056c8ff203d1d7e2f0c2`
- runner 配置 SHA-256：
  `dafa74de0426996e04aebd4d18b6b17922460124484c195de7d10b2feb4ce121`
- E3 组件 SHA-256：
  `1f622db5e87e592568d86e8a5467aab8493344cb6abc9252f3597f3fba1d831d`

试运行投影状态：

- 已完成必需“档位—种子”运行：`3/12`
- 未完成：V2、P1、P2 各三个种子
- 当前指纹内失败主运行：`0`
- 当前指纹内重复主运行：`0`
- 状态：`insufficient_pilot_coverage`
- `compute_gate_passed=false`
- `formal_execution_authorized=false`

## 已知限制

- 当前 PR 只完成算法性能试运行 runner，不包含 E1/E2/E4/E5 的全部实验编排。
- V2/P1/P2 尚未实测，V1 吞吐不能外推为正式总工时结论。
- E1/E2/E4/E5 执行器和有量纲速率尚未实现，因此即使12项算法试运行完成，
  也只能得到 `projection_incomplete`。
- 大规模超时进程树终止已实现，但尚未在 P2–P4 实际超时条件下验证。
- 排他锁已在 Windows 本地文件系统使用真实子进程验证；不支持多主机网络
  文件系统协调。
- 样本外评价、bootstrap、绘图和真实数据校准留给后续任务。

## 风险点

- `src/phase6_protocol.py` 的随机抽取顺序、截断和惩罚公式。
- `src/phase6_runner.py` 的三层时限累计、失败 checkpoint 和恢复指纹。
- `src/phase6_runner.py` 的冷/热代表重复选择与状态传递时点。
- `src/phase6_reporting.py` 的 LP 调用计数和完整试运行覆盖门槛。
- Windows 下外部看门狗终止进程树和原子替换行为。

## 下一步建议

1. 先复审本次三项补充修复，不立即运行 V2/P1/P2。
2. 复审通过后，实现 E1/E2/E4/E5 的实验族执行器和同量纲试运行速率。
3. 再完成 V2、P1、P2 的三个算法试运行种子，审查完整投影。
4. 门槛通过后，用独立 PR 将矩阵状态改为
   `frozen_for_formal_execution`。
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
9. 全局 registry 和失败文件是否可能在多进程运行时竞争，同一 `run_id`
   是否真正全程排他。
10. 正式种子门槛是否确实无法被候选矩阵绕过。
11. 吞吐计数与完整试运行覆盖规则是否过度乐观。
12. V1结果是否被正确限定为描述性试运行而非正式结论。
13. 失败预算、后续未运行预算和未执行算法重复是否全部有显式状态。
14. 科学配置哈希与 E3 组件哈希是否既稳定又覆盖所有 E3 科学依赖。
