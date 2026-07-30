# Phase 6 Family Pilots Handoff

## 任务目标

在实验矩阵冻结且 PR #12 修复 E2 状态语义后，使用固定 Gurobi 环境严格串行完成三个 pilot 种子的 E1、E2、E4、E5 family 试运行，为精简版 Phase 6 的计算量投影和后续 E3 规模 pilot 提供实测依据。

本轮仅执行 family pilot，没有运行 V2、P1、P2 E3 pilot，也没有运行任何正式种子。

## 分支和提交

- Branch: `agent/phase6-family-pilots-postfix`
- Base branch: `main`
- Base commit: `5abb3f907b001871c03ab9e783a33a09f99ab6f6`
- Handoff commit: pending
- PR: pending

## 固定运行环境

- Python: 3.12.10
- Interpreter: `D:\新建文件夹\项目交付\阶段3-4修复同步\phrase3\.venv-gurobi\Scripts\python.exe`
- Gurobi Optimizer: 13.0.2
- gurobipy: 13.0.2
- Pyomo: 6.10.1
- Pyomo interface: `gurobi_direct`
- Threads: 1
- NumPy: 2.5.1
- pandas: 3.0.5
- Academic license expiry: 2027-07-28
- HiGHS fallback: 禁止且未发生

## 执行顺序

所有运行严格串行，并按每个种子的 `E1 → E2 → E4 → E5` 顺序执行：

| Seed | E1 | E2 | E4 | E5 | 工作单元 |
|---:|---|---|---|---|---:|
| 2026072001 | optimal | optimal | optimal | optimal | 10/10 |
| 2026072002 | optimal | optimal | optimal | optimal | 10/10 |
| 2026072003 | optimal | optimal | optimal | optimal | 10/10 |
| 合计 | 3/3 | 3/3 | 3/3 | 3/3 | 30/30 |

12 条有效 run ID 均使用 `pilot_family_<family>_postfix_<seed>` 格式。当前 family 指纹下，registry 恰好包含每个 family、每个 seed 一条无父运行的 primary pilot；没有缺失、失败或重复。

PR #12 之前的 E1 成功和 E2 失败属于旧 family 代码指纹，继续永久保留，但未进入本轮投影。

## 指纹

- Scientific configuration:
  `3ac92ff09d85eebd99ba42dfaae54fb4b1ce7171d8e8a5f1bf8bceddb4524745`
- Family runner configuration:
  `983776a19e0a12937bc8a185b0fe5fdf76877d266445dcfce5f252d397a6ca8c`
- Family component code:
  `fb96854f96c13a3788548c78a0ac0cd1ca6b168cb5f21f74f334ca9b13ca5006`
- Locked environment:
  `0306c49cf953a79e3ade0fdf537e074dd17ddb942677333c62ef3f1bfb4782c2`

12 条运行的四类指纹完全一致。

## E1一致性

| Seed | 全场景扩展式目标 | 标准 C&CG 目标 | 绝对差 |
|---:|---:|---:|---:|
| 2026072001 | 27246.709055207586 | 27246.709055207582 | 3.638e-12 |
| 2026072002 | 14697.443536515952 | 14697.443536515952 | 0 |
| 2026072003 | 18045.099592489470 | 18045.099592489470 | 0 |

三组均满足冻结的精确一致性容差。

## E2策略比较

确定性均值方案在完整训练场景精确重评中均出现真实补救不可行：

| Seed | 不可行训练场景数 | 鲁棒目标 |
|---:|---:|---:|
| 2026072001 | 60 | null |
| 2026072002 | 52 | null |
| 2026072003 | 56 | null |

该结果按 PR #12 的语义完整保留，没有使用 Big-M 伪成本。零储备、三个固定比例和内生储备策略的精确训练评价均为最优，没有求解器失败或补救不可行。

| Seed | 内生储备目标 | 最佳固定比例目标 | 内生目标改善 |
|---:|---:|---:|---:|
| 2026072001 | 27529.469796428020 | 28231.734997358388 | 702.265200930367 |
| 2026072002 | 15373.788330159021 | 15572.516688160142 | 198.728358001121 |
| 2026072003 | 27024.972185553248 | 28062.214422340738 | 1037.242236787490 |

三组均通过“内生储备不劣于最佳固定比例”的结构门槛。

## E4样本外评价

E4 固定使用同种子 E2 内生储备方案，并在 2,000 个独立测试场景上求解精确补救：

| Seed | Optimal | Infeasible | Solver failure | Plan status |
|---:|---:|---:|---:|---|
| 2026072001 | 1940 | 60 | 0 | contains_infeasible_recourse |
| 2026072002 | 1960 | 40 | 0 | contains_infeasible_recourse |
| 2026072003 | 1907 | 93 | 0 | contains_infeasible_recourse |

计数恒等式均成立。因为存在真实补救不可行，均值成本、分位数和 CVaR 等成本聚合量按冻结规则保持 `null`；没有静默删除场景，也没有使用 Big-M 伪成本。

该结果是需要后续论文解释的重要 pilot 发现：训练场景鲁棒可行不保证有限样本外集合的相对完全补救。正式 E4 仍应同时报告补救可行率和不可行场景数，而不能只报告条件成功样本的成本。

## E5敏感性试运行

每个种子完成基准配置及 `shelf_life=1 × supply_reduction=0.4` 交互压力配置：

| Seed | Baseline | Interaction stress |
|---:|---:|---:|
| 2026072001 | 25422.393648275230 | 25697.625771009094 |
| 2026072002 | 12509.618901887568 | 12864.241153359982 |
| 2026072003 | 25639.950665216176 | 25974.111918722578 |

三组压力配置目标均高于各自基准，方向符合预期。

## 实测时间与投影

单条 run 墙钟时间：

- E1: 6.455–7.615 秒
- E2: 14.590–14.721 秒
- E4: 28.111–28.593 秒
- E5: 4.084–4.132 秒

按各 family 三个 pilot 中最保守的完整工作单元吞吐率：

| Family | 正式工作单元 | 投影小时 |
|---|---:|---:|
| E1 | 45 | 0.0952 |
| E2 | 180 | 0.1227 |
| E4 | 90 | 0.7148 |
| E5 | 75 | 0.0430 |
| Family合计 | 390 | 0.9757 |

这些时间仅用于冻结门槛的工程投影，不作为算法性能结论。

## 总投影和正式授权

刷新后的总投影记录：

- Matrix status: `frozen_for_formal_execution`
- Family projection: E1、E2、E4、E5 均为 `projected`
- E3: `awaiting_complete_pilots`
- E3 pilot coverage: `3/12`
- Missing E3 pilots: V2、P1、P2 各三个种子
- E3 failed primary runs: 0
- E3 duplicate primary runs: 0
- Projection status: `projection_incomplete`
- `compute_gate_passed=false`
- `formal_execution_authorized=false`

因此，本轮完成不授权正式实验。

## 验证命令

```text
.\.venv-gurobi\Scripts\python.exe -m src.environment_check --smoke-test
passed

.\.venv-gurobi\Scripts\python.exe -m compileall -q src tests
passed

.\.venv-gurobi\Scripts\python.exe -m pytest -q
111 passed in 37.25s

git diff --check
passed
```

## 输出与提交边界

原始 `result.json`、`manifest.json`、checkpoint、registry、投影和日志保存在 D 盘 `outputs/experiments/phase6/`，受 `.gitignore` 管理，不提交 GitHub。本 PR 只提交 handoff，不提交大型实验输出。

仓库中既有的未跟踪 `outputs/gurobi_validation/` 和 `outputs/tmp/` 与本任务无关，未修改、未删除、未加入提交。

## ChatGPT审查清单

1. 12条 run 是否严格遵循每个种子的 E1→E2→E4→E5 顺序；
2. 30个工作单元是否全部完成，是否存在重复或失败 primary；
3. 四类指纹是否在12条运行中完全一致；
4. E1扩展式与标准 C&CG 是否在冻结容差内一致；
5. 确定性训练不可行是否正确保留为 `null` 鲁棒目标；
6. 其他五类 E2 策略是否均为精确最优；
7. 内生储备结构门槛是否三组均通过；
8. E4不可行场景是否没有被静默删除或赋 Big-M 成本；
9. 投影单位是否仍为各 family 的完整工作单元；
10. 正式授权是否仍正确保持为 false；
11. 是否未运行 V2、P1、P2或正式种子；
12. 大型输出是否未提交。

## 下一步

本 handoff 经独立复审并合并后，下一步才是按冻结顺序运行 E3 的 V2 三个 pilot。V2 完成并复审后，再根据既定门槛决定是否进入 P1；P2 必须额外通过 P1 规模推进门槛。正式种子仍未获准。
