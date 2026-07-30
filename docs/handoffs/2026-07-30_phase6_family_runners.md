# Phase 6 E1/E2/E4/E5 Runner Handoff

## 任务目标

补齐精简版 Phase 6 实验矩阵的 E1、E2、E4、E5 执行器、失败保留、独立工作量投影和正式运行门槛，同时保持已完成 V1 E3 pilot 的科学指纹有效。

## 分支和提交

- Branch: `agent/phase6-experiment-runners`
- Base branch: `main`
- Base SHA: `c0eda012ccacee282e499b93751daf6a4b3f2e6b`
- Implementation SHA: `088f384625a5bc22c3249dfd61c0a1e90ca05c70`
- Test SHA: `f3e5e0bd94e577dd2c34d7891aba02fbe7ecc4bd`
- PR: pending

## 修改内容

### 配置

- 新增 `configs/phase6_family_runner.yaml`；
- 固定 family pilot 的 E1 → E2 → E4 → E5 顺序、每类代表工作单位和计划墙钟时限；
- 只允许 `gurobi`、`gurobi_direct` 和 `Threads=1`。

### 执行器

- E1：扩展式与标准 C&CG 完整精确一致性门槛；
- E2：六种策略统一训练场景独立补救重评和内生储备结构优势检查；
- E4：复用已完成 E2 第一阶段方案，不在测试集重新优化；
- E5：11 个 OFAT 与 4 个库存—市场交互配置的正式计划枚举。

### 工程

- 每个 family run 使用全生命周期排他锁；
- 每个计划使用独立受监控子进程和外部墙钟；
- 原子写入针对 Windows `PermissionError` 做有界重试；
- 失败终态不可覆盖，失败后的计划显式标记未运行；
- 新增不会读取大型结果文件的 `phase6_family_status`；
- manifest 在最终结果写入后计算结果文件 SHA-256。

### 投影

- E1、E2、E4、E5 按完整 family 计划/小时投影；
- 每类要求三个冻结 pilot 种子恰好各有一条完整最优主运行；
- 缺失、失败、重复、科学配置/runner/代码/环境指纹不一致均阻止授权；
- 与现有 E3 投影合并后才计算总工时门槛。

## 关键实现决策

- 新 family 文件不加入 `PHASE6_E3_COMPONENT_FILES`，避免无关代码使 V1 E3 pilot 失效；
- E2 所有策略均使用独立补救模型重评，避免解释扩展式内部非最坏场景变量；
- E4 补救不可行是科学结果而非 runner 异常，但聚合成本指标必须为空；
- E4 求解器失败是工程失败，会停止当前 family run；
- family pilot 必须按同一种子的 E1 → E2 → E4 → E5 顺序运行；
- 矩阵仍为候选状态，本提交不授权任何正式种子。

## 修改文件

- `configs/phase6_family_runner.yaml`
- `src/phase6_families.py`
- `src/phase6_family_runner.py`
- `src/phase6_family_worker.py`
- `src/phase6_family_status.py`
- `src/run_phase6_family.py`
- `tests/test_phase6_families.py`
- `tests/test_phase6_family_runner.py`
- `docs/phase6_family_runners.md`
- 本 handoff

## 验证结果

实际执行：

```text
.\.venv-gurobi\Scripts\python.exe -m compileall -q src tests
结果：通过

.\.venv-gurobi\Scripts\python.exe -m pytest -q
结果：94 passed in 35.02s

.\.venv-gurobi\Scripts\python.exe -m pytest -q --ignore=tests/test_run_phase5.py
结果：88 passed in 25.47s

.\.venv-gurobi\Scripts\python.exe -m pytest -q tests/test_run_phase5.py
结果：6 passed in 10.64s
```

真实 Gurobi 开发级烟雾验证：

```text
Gurobi Optimizer / gurobipy: 13.0.2
Pyomo interface: gurobi_direct
Threads: 1
D0 extensive objective: 6364.75854901043
D0 standard C&CG objective: 6364.75854901043
objective difference: 0.0
C&CG iterations: 4
V2 E5 baseline status: optimal
V2 E5 baseline objective: 18381.98119768014
```

V1 E3 保留检查：

```text
3/3 post-PR #8 V1 runs: optimal
9/9 budget pairs: optimal
18/18 cold/warm algorithm executions: optimal
maximum cold/warm objective difference: 1.8189894035458565e-12
current E3 component SHA-256:
bce43075dd91053b5b2c4fa2942fa84bea02654be17d2f10c99df08176248342
all three V1 manifests use the same E3 and scientific fingerprints: yes
```

没有运行新的 family pilot、V2/P1/P2 E3 pilot、P3/P4 或正式种子。

## CI 状态

- Draft PR 创建前：pending
- GitHub Actions：pending

## 已知限制

- 当前矩阵状态仍为 `candidate_for_freeze_pending_review`；
- E1/E2/E4/E5 三种子 pilot 尚未执行；
- V2/P1/P2 E3 pilot 尚未执行；
- 完整计算量投影和正式授权仍应为 `projection_incomplete` / `false`；
- 真实校准轨道仍等待独立协议；
- 不实现 P3/P4、并行 oracle、严格二进制 FIFO 或自动合并。

## 风险点

ChatGPT 复审时应重点检查：

1. E2 六策略是否确实使用同一完整训练场景独立重评；
2. E4 是否严格禁止测试集重优化及静默删除失败场景；
3. E4 不可行与求解失败的状态语义是否正确；
4. family 投影的工作单位是否有量纲一致；
5. 三种子缺失、失败和重复是否都会阻止授权；
6. E4 是否只能解析唯一、同指纹的 E2 方案；
7. formal gate 是否在计划解析和场景生成前生效；
8. family 代码是否确实不改变 E3 指纹；
9. manifest 的最终结果哈希是否可复核；
10. 当前代码是否可能绕过 Gurobi-only 或单线程约束。

## 下一步建议

1. 复审并合并本 Draft PR；
2. 通过独立受审提交把矩阵状态改为 `frozen_for_formal_execution`；
3. 固定本 family 代码和配置指纹；
4. 串行运行三个种子的 E1 → E2 → E4 → E5 family pilot；
5. 串行运行 V2、P1、P2 的 E3 pilot，保留已通过的 V1；
6. 审查完整投影；仅在门槛通过后申请正式种子授权。
