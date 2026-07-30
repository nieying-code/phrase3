# Phase 6 Experiment Matrix Freeze Handoff

## 任务目标

通过独立、受审的小型提交，将精简版 Phase 6 实验矩阵从候选状态正式
冻结，同时证明生命周期状态变化不会改变科学配置指纹。矩阵冻结只满足
正式运行的第一层门槛，不授权任何正式种子。

## 分支和提交

- Branch: `agent/phase6-freeze-matrix`
- Base branch: `main`
- Base SHA: `d2f6f1c60c484c734b0795c5d94795b642f70b22`
- Freeze commit SHA: `6f67e4ea0127c29eb49f5d6e60c9fae0046af70f`
- PR: `pending`

## 修改内容

### 矩阵状态

- `configs/phase6_experiment_matrix.yaml`：
  - `status` 从 `candidate_for_freeze_pending_review` 改为
    `frozen_for_formal_execution`；
  - `revised_on` 更新为 `2026-07-30`；
  - 未修改任何规模、种子、预算、敏感性、算法或统计参数。

### 自动验证

- 矩阵专项测试现在要求正式冻结状态；
- 科学哈希测试显式比较冻结矩阵与原候选生命周期字段；
- 保留候选状态阻止正式种子的边界测试；
- 冻结后若缺少完整 pilot 投影，family formal runner 仍在计划解析和场景
  生成前拒绝执行。

### 文档

- 同步更新实验矩阵、E3 runner 和 family runner 的当前状态；
- 明确 `frozen_for_formal_execution` 不等于
  `formal_execution_authorized=true`。

## 指纹验证

实际计算结果：

```text
runner scientific hash, frozen:
3ac92ff09d85eebd99ba42dfaae54fb4b1ce7171d8e8a5f1bf8bceddb4524745

runner scientific hash, candidate lifecycle fields:
3ac92ff09d85eebd99ba42dfaae54fb4b1ce7171d8e8a5f1bf8bceddb4524745

family scientific hash, frozen:
3ac92ff09d85eebd99ba42dfaae54fb4b1ce7171d8e8a5f1bf8bceddb4524745

family scientific hash, candidate lifecycle fields:
3ac92ff09d85eebd99ba42dfaae54fb4b1ce7171d8e8a5f1bf8bceddb4524745

E3 component hash:
bce43075dd91053b5b2c4fa2942fa84bea02654be17d2f10c99df08176248342
```

因此状态冻结不会使现有三条 V1 E3 pilot 失效。

## 验证结果

实际执行：

```text
.\.venv-gurobi\Scripts\python.exe -m compileall -q src tests
结果：通过

.\.venv-gurobi\Scripts\python.exe -m pytest -q \
  tests/test_phase6_experiment_matrix.py \
  tests/test_phase6_reporting.py \
  tests/test_phase6_protocol.py \
  tests/test_phase6_families.py \
  tests/test_phase6_family_runner.py
结果：47 passed in 7.96s

.\.venv-gurobi\Scripts\python.exe -m pytest -q \
  --ignore=tests/test_run_phase5.py
结果：103 passed in 26.46s

.\.venv-gurobi\Scripts\python.exe -m pytest -q tests/test_run_phase5.py
结果：6 passed in 9.86s
```

## 执行边界

本任务没有运行：

- family pilot；
- V2、P1 或 P2 E3 pilot；
- P3 或 P4；
- 任何正式种子。

即使本 PR 合并，正式实验仍必须保持未授权，直到全部 pilot、指纹、计算量
和规模推进门槛通过。

## ChatGPT 审查清单

1. 本 PR 是否只改变生命周期状态、测试期望和对应文档；
2. 是否有任何科学参数被修改；
3. 候选与冻结状态的科学配置哈希是否严格一致；
4. E3 组件哈希是否保持不变；
5. 候选状态测试是否仍能阻止正式种子；
6. 冻结状态下缺少投影时是否仍在计划解析前阻止 formal runner；
7. 是否运行或提交了任何未授权实验输出。

## 下一步建议

本 PR 复审并合并后，使用当前冻结矩阵和新 family 指纹，严格按每个种子的
`E1 → E2 → E4 → E5` 顺序串行运行三个 family pilot。family pilot
完成、形成独立 handoff 和 Draft PR 并通过复审后，才进入 V2 E3 pilot。
