# Phase 6 E2 Infeasible Policy Handoff

## 任务目标

修复冻结后 family pilot 首次实际执行暴露的 E2 状态语义缺口：确定性均值方案在完整训练场景精确重评时可能出现真实补救不可行，该科学结果必须保留，不能被误报为求解器或 runner 异常。

## 分支和提交

- Branch: `agent/phase6-family-pilots`
- Base branch: `main`
- Base commit: `b0b8cac7fb0b931832a4072ae31c26cee7a990a7`
- Implementation commit: `bf8525533a381b146c96b5e6f2b65309cf5992c9`
- PR: https://github.com/nieying-code/phrase3/pull/12

## 实际运行证据

冻结后的 family pilot 严格串行启动，未运行 V2、P1、P2 或正式种子。

1. `pilot_family_e1_postfreeze_2026072001`
   - status: `optimal`
   - completed work units: `1/1`
2. `pilot_family_e2_postfreeze_2026072001`
   - status: `worker_exception`
   - completed work units: `0/6`
   - failed plan: `E2P_V2_2026072001_b01_deterministic_mean`
   - exact evaluation status: `infeasible_recourse`

E2 失败后立即停止，没有启动 E4、E5 或后续种子。失败 run ID 保持不可变，也没有使用相同 ID 重试。

## 根因

`evaluate_first_stage()` 正确区分了：

- `optimal`
- `infeasible_recourse`
- `oracle_failure`

但 E2 worker 原先要求所有策略的完整训练评价必须为 `optimal`。因此，确定性均值模型生成的第一阶段方案一旦在某个完整训练场景中因库存容量等物理约束出现真实补救不可行，worker 就把它升级为 `RuntimeError`，导致整条 family run 中止。

这与冻结设计中的“所有策略使用相同完整训练场景精确重评”不一致。确定性策略的不可行性本身是需要报告的实验结果，不是求解器失败。

## 修改内容

### E2 worker

- 允许 `deterministic_mean` 的精确训练评价返回 `infeasible_recourse`。
- 该计划仍记为执行完成，保留第一阶段方案、原生目标、不可行场景数和评价状态。
- `robust_objective` 保持 `null`，不使用 Big-M 伪成本。
- `oracle_failure` 仍然是阻断性失败。
- 零储备、固定比例和内生储备等鲁棒策略若出现补救不可行，仍视为模型一致性错误并阻断。

### E2结构门槛

- 内生储备和三个固定比例策略必须具有最优精确训练评价及有限鲁棒目标。
- 内生储备不劣于最佳固定比例的结构检查保持不变。
- 确定性均值策略的不可行评价不参与该结构门槛。

### 测试和文档

- 新增确定性策略真实补救不可行仍被完整保留的 worker 测试。
- 新增整条 E2 runner 在该情形下仍完成 `6/6` 工作单元的测试。
- 文档明确区分科学不可行与工程/求解器失败。

## 验证结果

实际执行：

```text
.\.venv-gurobi\Scripts\python.exe -m pytest tests/test_phase6_family_runner.py tests/test_phase6_families.py -q
28 passed in 5.52s

.\.venv-gurobi\Scripts\python.exe -m pytest -q
111 passed in 36.67s

git diff --check
passed（仅有 Windows LF/CRLF 提示）
```

运行环境预检：

- Python: 3.12.10
- Gurobi Optimizer: 13.0.2
- gurobipy: 13.0.2
- Pyomo interface: `gurobi_direct`
- Threads: 1

## 指纹与已有结果影响

- 未修改冻结实验矩阵。
- 未修改 E3 模型、C&CG、SPW-C&CG、E3 worker 或 E3 runner。
- 已有三条 V1 E3 pilot 继续有效。
- family 组件代码哈希将按设计变化，因此本次 E1 成功结果和 E2 失败结果均不能进入修复后的 family 投影门槛。
- 合并后必须使用全新 run ID 从该种子的 E1 开始重新执行 family 顺序。

## ChatGPT复审重点

1. 确定性均值方案的真实补救不可行是否被完整保留而非静默删除；
2. `robust_objective=null` 是否避免了 Big-M 伪成本；
3. `oracle_failure` 是否仍会阻断；
4. 鲁棒策略的意外补救不可行是否仍被当作一致性错误；
5. 内生储备与固定比例的结构门槛是否仍只比较可验证的精确鲁棒目标；
6. E3 指纹和已有 V1 pilot 是否确实不受影响；
7. 失败 run ID 是否保持不可变。

## 下一步

本 PR 通过复审并合并后：

1. 从最新 `main` 创建新的 family pilot 分支；
2. 使用全新 run ID，从种子 `2026072001` 的 E1 重新开始；
3. 严格执行 `E1 → E2 → E4 → E5`；
4. 再依次执行另外两个 pilot 种子；
5. 完成 12 条 family run 后停止，整理投影和独立 handoff；
6. 暂不启动 V2、P1、P2 或正式种子。
