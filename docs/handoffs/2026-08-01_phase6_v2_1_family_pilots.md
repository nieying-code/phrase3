# Phase 6 v2.1 Family Pilot Handoff

## 任务目标

在相对完全补救模型的 V1 E3 pilot 通过复审并合并后，使用同一隔离输出根目录和三个冻结 pilot 种子，严格按每个种子的 `E1 → E2 → E4 → E5` 顺序运行 family pilot。本批次只验证 family 执行器、策略比较、样本外评价和敏感性配置，不启动 V2、P1、P2 或正式种子。

## 分支和提交

- Branch: `agent/phase6-v2-1-family-pilots`
- Base: `8d72b36c38eab93986b6e267946b09b4d34c7c3e`（PR #16 合并后的 `main`）
- Execution tree: `faa3948e8381525992a54463ef25b1887cb8543c`
- Commit SHA: pending
- Draft PR: pending
- CI: pending

## 隔离输出基线

- Output root: `outputs/phase6_v21_rr_clean`
- 该根目录已包含经复审的 V1 E3 pilot，执行前 E3 投影为 `3/12`。
- Family registry 在本批次开始前为空；旧模型、旧指纹和旧 family pilot 没有进入该根目录。
- 执行开始时 Git 已跟踪文件修改数为 0；未跟踪内容仅为 Git 忽略的实验输出目录。
- E4 按设计读取并二次校验同一输出根目录、同一种子的 E2 内生储备方案；其余历史输出目录均未作为运行输入。

## 环境与指纹

| 项目 | 值 |
|---|---|
| Matrix status | `frozen_for_formal_execution` |
| Scientific config SHA-256 | `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3` |
| E3 component SHA-256 | `7713671bab67eec8d99fdf776f1d645740d09d020ef31b55513ccc80595f951f` |
| Family component SHA-256 | `5803afd60d39a2e982d9b2c879453ef2d4e21755fcb46791810a1e1de8e5076f` |
| Family config SHA-256 | `983776a19e0a12937bc8a185b0fe5fdf76877d266445dcfce5f252d397a6ca8c` |
| Environment SHA-256 | `0306c49cf953a79e3ade0fdf537e074dd17ddb942677333c62ef3f1bfb4782c2` |
| Python | `3.12.10` |
| Gurobi / gurobipy | `13.0.2 / 13.0.2` |
| Pyomo interface | `gurobi_direct` |
| Threads | `1` |
| HiGHS fallback | 禁止且未发生 |

## 执行顺序与结果

三个种子均严格依次执行：

1. `2026072001`: E1、E2、E4、E5
2. `2026072002`: E1、E2、E4、E5
3. `2026072003`: E1、E2、E4、E5

汇总结果：

| Family | Primary runs | Work units | Result |
|---|---:|---:|---|
| E1 | 3/3 | 3/3 | 全部 optimal |
| E2 | 3/3 | 18/18 | 全部 optimal |
| E4 | 3/3 | 3/3 | 全部 optimal |
| E5 | 3/3 | 6/6 | 全部 optimal |
| Total | 12/12 | 30/30 | 全部 optimal |

不存在失败、超时、重复 primary 或 parent/diagnostic retry。

## 科学验收

### E1：V1 模型一致性

| Seed | Extensive objective | Standard C&CG objective | Difference |
|---:|---:|---:|---:|
| 2026072001 | 25431.602135889087 | 25431.602135889087 | 0.0 |
| 2026072002 | 12593.369449515683 | 12593.369449515683 | 0.0 |
| 2026072003 | 16465.082639466546 | 16465.082639466546 | 0.0 |

### E2：V2 六策略训练场景评价

每个种子均完成确定性均值、零储备、三个固定储备比例和内生储备六种策略。18 个精确训练评价全部为 `optimal`，补救不可行数和求解器失败数均为 0。三个种子下内生储备目标均不劣于最佳测试固定比例目标。

### E4：V2 内生储备方案样本外评价

| Training seed | Test seed | Optimal / total | Infeasible | Solver failure | Mean cost | P95 | CVaR95 | Service level |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026072001 | 2036072001 | 2000/2000 | 0 | 0 | 9234.831483 | 16983.168239 | 20760.664760 | 0.714102 |
| 2026072002 | 2036072002 | 2000/2000 | 0 | 0 | 4999.396538 | 12451.527077 | 16396.645521 | 0.866405 |
| 2026072003 | 2036072003 | 2000/2000 | 0 | 0 | 8959.085400 | 16242.489542 | 18710.013323 | 0.718268 |

全部 6000 个样本外补救模型均最优可行，`plan_oos_status=complete_feasible`。`early_disposal`、`expired_waste` 和 `total_disposal` 指标均为有限值，且总处置量等于两类处置之和。

### E5：V2 敏感性配置

三个种子均完成 `baseline` 与 `interaction_life_1_supply_0.4` 两个配置，共 6/6 个工作单元，全部为 `optimal`。

## 投影状态

Family 的 E1、E2、E4、E5 均已形成维度一致的实测投影；E3 仍为 `awaiting_complete_pilots`，因为当前只完成 V1：

- E3 coverage: `3/12`
- Projection status: `projection_incomplete`
- `compute_gate_passed=false`
- `formal_execution_authorized=false`

这是预期状态，不构成失败，也不授权正式实验。

## 机器审计

紧凑审计文件：`docs/handoffs/2026-08-01_phase6_v2_1_family_pilots_audit.json`

该文件记录 12 个 run 的 result、manifest 和有界状态摘要 SHA-256、30 个工作单元计数、E1/E2/E4/E5 科学验收摘要、全局 registry/projection 哈希、环境与三类组件指纹。大型原始结果继续保留在 D 盘并由 Git 忽略。

## 验证结果

```text
.venv-gurobi\Scripts\python.exe -m pytest -q tests\test_phase6_family_pilot_audit.py
1 passed in 0.06s

.venv-gurobi\Scripts\python.exe -m pytest -q
128 passed in 27.97s

.venv-gurobi\Scripts\python.exe -m compileall -q src tests
passed

git diff --check
passed
```

CI：pending（Draft PR 创建后更新）。

## 已知限制与停止边界

- Family pilot 是工程与小规模科学正确性证据，不是正式统计推断。
- E4 仅使用三个 pilot 训练种子；正式 E4 的统计定位仍遵循冻结矩阵。
- 本批次未运行 V2、P1、P2 或任何正式种子。
- PR 通过 ChatGPT 复审并由用户手动合并前，不启动 V2 E3 pilot。
- 下一步仅为 V2 E3 pilot：3 个种子 × 3 个预算 × 2 种算法 × 3 次技术重复，共 54 次算法执行。

## ChatGPT 审查清单

1. 12 个 primary run 和 30 个工作单元是否完整且全部最优。
2. 是否严格遵守每个种子的 E1 → E2 → E4 → E5 顺序。
3. E1 扩展式与标准 C&CG 是否逐种子一致。
4. E2 是否覆盖六种策略，且不存在补救不可行或求解器失败。
5. E4 的 6000 个样本外场景是否全部最优可行，尾部成本和服务水平是否有限。
6. 提前处置、到期损耗和总处置是否保持一致且不重复。
7. E5 两个 pilot 配置是否逐种子完成。
8. 三类科学/组件指纹和环境指纹是否与冻结版本一致。
9. 投影是否正确停留在 E3 `3/12` 且正式授权为 `false`。
10. 是否没有提交大型输出或提前运行后续实验。
