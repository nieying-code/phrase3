# Phase 6 repro-v3 family pilot handoff

## 任务目标

在 PR #22 建立的可复现执行基线和 PR #23 已批准的 V1 E3 pilot 之后，严格串行重跑三个试运行种子的 E1、E2、E4、E5 family pilot，验证相对完全补救修复在训练内和样本外评价中的有效性，并为后续 V2 E3 pilot 恢复 family 投影依据。

## 分支和提交

- Branch: `agent/phase6-family-repro-v3`
- Base: merged `main` commit `98ef223755fb9d87d8de621b00d5a874c50c6175`
- Results commit: `e98d9ec0a65e717340d1bf48116d7f21e1e98fd0`
- Final PR head: pending
- Pull request: https://github.com/nieying-code/phrase3/pull/24
- CI: pending

## 执行边界与环境

- 输出根目录：`outputs/phase6_v21_repro_v3`
- 三个种子均严格按 `E1 → E2 → E4 → E5` 串行执行。
- 未启动 V2、P1、P2 E3 pilot，也未启动任何正式种子。
- Python `3.12.10`；Gurobi Optimizer / gurobipy `13.0.2`；Pyomo `gurobi_direct`；`Threads=1`；无 HiGHS 回退。
- 执行提交为 `98ef223755fb9d87d8de621b00d5a874c50c6175`，tree 为 `551678c5045a93dafc2cc146d44ef000991ef64d`。
- 运行开始时 tracked 修改数为 0、untracked 路径为空，12 个 manifest 均记录干净工作树。

## 指纹

- Scientific configuration: `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3`
- E3 component: `fd0dc3ea77f850615502005e2caf9f3b7c0259d7c11a9efc7e2a30025c404083`
- Family component: `92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e`
- Family runner config: `983776a19e0a12937bc8a185b0fe5fdf76877d266445dcfce5f252d397a6ca8c`
- Environment: `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`

## 结果

| 实验族 | Primary runs | 工作单元 | 状态 |
| --- | ---: | ---: | --- |
| E1 | 3/3 | 3/3 | 全部 optimal |
| E2 | 3/3 | 18/18 | 全部 optimal |
| E4 | 3/3 | 3/3 | 全部 optimal |
| E5 | 3/3 | 6/6 | 全部 optimal |
| 合计 | 12/12 | 30/30 | 全部 optimal |

- E1：三个种子的扩展式目标与标准 C&CG 目标差均为 `0.0`，两侧精确补救评价均无不可行场景。
- E2：18 个策略方案全部最优；训练场景补救不可行数为 0，求解器失败数为 0。
- E4：三个训练种子分别使用独立测试种子 `2036072001/2/3`；共 6000 个样本外场景全部最优，补救不可行数为 0，求解器失败数为 0；均值成本、P95、CVaR95、服务水平及三类处置指标均为有限值。
- E5：三个种子的 `baseline` 与 `interaction_life_1_supply_0.4` 共 6 个配置全部最优。
- 无失败 primary、重复 primary 或带 `parent_run_id` 的诊断重试。

详细逐 run 哈希、E1 数值、E4 指标和投影状态见 [机器审计 JSON](./2026-08-02_phase6_repro_v3_family_pilots_audit.json)。原始输出、场景和日志保留在 D 盘受控输出根目录，不提交 GitHub。

## 投影与停止状态

- Family 投影：E1、E2、E4、E5 均为 `projected`。
- E3 仍只有已批准 V1 的 `3/12`，状态为 `awaiting_complete_pilots`。
- 总投影状态：`projection_incomplete`。
- `compute_gate_passed=false`。
- `formal_execution_authorized=false`。

本批次按授权边界停止。PR 复审并由用户手动合并前，不运行 V2 E3 pilot。

## 验证

- 审计专项测试：`.venv-gurobi\\Scripts\\python.exe -m pytest tests\\test_phase6_repro_v3_family_pilot_audit.py -q` → `1 passed in 0.05s`
- 完整回归：`.venv-gurobi\\Scripts\\python.exe -m pytest -q` → `155 passed in 36.05s`
- `git diff --check`：通过
- GitHub Actions：pending

## 修改文件

- `docs/handoffs/2026-08-02_phase6_repro_v3_family_pilots.md`：本次 handoff。
- `docs/handoffs/2026-08-02_phase6_repro_v3_family_pilots_audit.json`：紧凑机器审计快照。
- `tests/test_phase6_repro_v3_family_pilot_audit.py`：机器审计结构、计数、数值和门槛测试。

## 下一步建议

ChatGPT 复审本 PR 并由用户手动合并后，下一批仅运行 V2 E3 pilot：三个 pilot 种子、三个预算、冷/热两种算法、每种算法三次技术重复，共 54 次算法执行。V2 完成后应再次停止并独立复审，不自动进入 P1。

## ChatGPT 审查清单

1. 12 个 primary run 和 30 个工作单元的计数是否闭合；
2. 三个种子是否均遵守 E1 → E2 → E4 → E5 顺序；
3. E1 扩展式与标准 C&CG 是否一致；
4. E2 是否没有 `unexpected_infeasible_recourse` 或 solver failure；
5. E4 是否 6000/6000 场景最优且三类处置指标关系成立；
6. E4 是否使用同种子、哈希验证的 E2 内生储备方案；
7. 三类科学/组件指纹和环境指纹是否匹配当前批准基线；
8. E3 投影是否仍为 3/12，正式授权是否保持 false；
9. 是否未提交大型结果或启动未授权实验。
