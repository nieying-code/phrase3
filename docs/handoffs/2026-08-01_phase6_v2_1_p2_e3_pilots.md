# Phase 6 v2.1 P2 E3 Pilot and Compute-Gate Handoff

## 任务目标

在 P1 E3 pilot 通过复审并由用户合并 PR #19 后，使用冻结矩阵完成
P2 E3 pilot。P2 是五物资、十二期、1000 个训练场景的描述性压力档位。
本批次仅运行三个 pilot 种子，完成后立即停止实验，并对全部 E3 与 family
pilot 执行完整计算门槛审计；没有启动任何正式种子。

## 分支和提交

- Branch: `agent/phase6-v2-1-p2-e3-pilots`
- Execution SHA: `ce9d5e32fb60e444d90550be07deb61641544f4c`
- Execution tree: `c5d420fab08c2b6551db6ead9358d8c6f9f12ade`
- Merged `main` SHA: `c18ff242756ca9fad43b17f21511ca24e9f6a345`
- Merged `main` tree: `c5d420fab08c2b6551db6ead9358d8c6f9f12ade`
- Validated result commit: `c33139449b707855714ccfa819ddd1367d7831b9`
- Draft PR: https://github.com/nieying-code/phrase3/pull/20
- Results CI: https://github.com/nieying-code/phrase3/actions/runs/30700159405
  (`125 passed + 6 passed`)

开始运行时 GitHub 网络短暂不可达，因此本地分支从 PR #19 的最终 head 创建。
网络恢复后已获取合并后的 `main`；两者 Git tree 完全相同，故运行代码字节与
合并后的主线一致。

## 环境和指纹

| 项目 | 值 |
|---|---|
| Matrix status | `frozen_for_formal_execution` |
| Scientific config SHA-256 | `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3` |
| E3 component SHA-256 | `7713671bab67eec8d99fdf776f1d645740d09d020ef31b55513ccc80595f951f` |
| Family component SHA-256 | `5803afd60d39a2e982d9b2c879453ef2d4e21755fcb46791810a1e1de8e5076f` |
| Environment SHA-256 | `0306c49cf953a79e3ade0fdf537e074dd17ddb942677333c62ef3f1bfb4782c2` |
| Python | `3.12.10` |
| Gurobi / gurobipy | `13.0.2 / 13.0.2` |
| Pyomo interface / threads | `gurobi_direct / 1` |
| HiGHS fallback | `false` |

执行前 tracked 修改数为 0。manifest 的 `working_tree_dirty=true` 来自未跟踪
输出目录；没有未提交的模型、矩阵、runner 配置或依赖锁参与执行。
`outputs/phase6_v21_rr_clean/` 是受控读写根目录，读取已经批准的 V1、V2、
P1 和 family 前序 registry/projection 制品，并写入本次 P2 结果。其他历史输出
目录没有作为输入。

## P2 执行范围

严格串行运行以下全新 primary run ID：

- `pilot_rr_v21_e3_p2_primary_2026072001`
- `pilot_rr_v21_e3_p2_primary_2026072002`
- `pilot_rr_v21_e3_p2_primary_2026072003`

每条 run 含三个预算、标准 C&CG 冷启动和 SPW-C&CG 热启动，各一次计时：

```text
3 seeds × 3 budgets × 2 algorithms = 18 algorithm executions
```

## P2 数值结果

| Seed | Budget factor | Cold objective | Warm objective | Difference | Cold/Warm seconds | Iterations |
|---:|---:|---:|---:|---:|---:|---:|
| 2026072001 | 0.90 | 230431.306279 | 230431.306279 | 0.0 | 56.2774 / 56.0568 | 1 / 1 |
| 2026072001 | 1.10 | 189431.889361 | 189431.889361 | 0.0 | 54.9873 / 54.5998 | 1 / 1 |
| 2026072001 | 1.30 | 148642.529382 | 148642.529382 | 0.0 | 120.9047 / 119.4891 | 2 / 2 |
| 2026072002 | 0.90 | 208974.699269 | 208974.699269 | 0.0 | 118.9814 / 117.4970 | 2 / 2 |
| 2026072002 | 1.10 | 168022.145958 | 168022.145958 | 0.0 | 121.8844 / 55.9361 | 2 / 1 |
| 2026072002 | 1.30 | 127269.655825 | 127269.655825 | 0.0 | 120.3564 / 56.6474 | 2 / 1 |
| 2026072003 | 0.90 | 238191.583006 | 238191.583006 | 0.0 | 185.6252 / 187.7035 | 3 / 3 |
| 2026072003 | 1.10 | 197154.765114 | 197154.765114 | 0.0 | 186.8495 / 56.8230 | 3 / 1 |
| 2026072003 | 1.30 | 156358.340301 | 156358.340301 | 0.0 | 185.9909 / 57.5923 | 3 / 1 |

汇总：3/3 primary、9/9 冷热预算配对、18/18 算法执行均为
`optimal`；最大冷热目标差为 `0.0`；峰值内存为 `220.617188 MB`。
不存在补救不可行、solver failure、timeout、重复 primary、parent run 或
diagnostic retry。`early_disposal`、`expired_waste` 和 `total_disposal`
字段均存在。

## 完整 E3 和 family 覆盖

- E3: V1/V2/P1/P2 各 3 条，合计 `12/12` primary；
- E3 missing/failed/duplicate/diagnostic: `0/0/0/0`；
- Family: `12/12` runs、`30/30` work units；
- E1、E2、E3、E4、E5 的投影状态均为 `projected`；
- family 制品在最终门槛聚合时重新校验 manifest 和 result 哈希。

最后一条 E3 run 先写出 E3 投影；随后调用既有 family 聚合器，将已经批准的
family pilot 投影重新合并。该步骤只核验和汇总已有制品，没有运行模型。

## 完整计算门槛

| 实验族 | 预计墙钟小时 |
|---|---:|
| E1 | 0.030597 |
| E2 | 0.129666 |
| E3 | 8.861969 |
| E4 | 0.763491 |
| E5 | 0.043979 |
| Total | 9.829702 |

- 总预计墙钟 `9.829702 h ≤ 168 h`；
- 最大单实验族为 E3，`8.861969 h ≤ 72 h`；
- `compute_gate_passed=true`；
- `formal_execution_authorized=true`；
- Projection status: `passed`。

这里的 `formal_execution_authorized=true` 仅表示冻结矩阵中的机器门槛已经满足。
按照项目的人审流程，本 PR 复审通过并由用户明确授权前，所有正式种子仍保持停止。

## 机器审计

`docs/handoffs/2026-08-01_phase6_v2_1_p2_e3_pilots_audit.json`
记录 P2 3/9/18 计数、逐预算目标和时间、制品哈希、三类指纹、完整 12/12
E3 覆盖、12/30 family 覆盖、分实验族投影与停止边界。大型结果、训练场景和
日志只保留在 D 盘，不进入 Git。

## 验证结果

```text
.venv-gurobi\Scripts\python.exe -m pytest -q tests\test_phase6_p2_e3_pilot_audit.py
1 passed in 0.04s

.venv-gurobi\Scripts\python.exe -m pytest -q
131 passed in 28.45s

.venv-gurobi\Scripts\python.exe -m compileall -q src tests
passed

git diff --check
passed
```

GitHub Actions run `30700159405` 对结果提交
`c33139449b707855714ccfa819ddd1367d7831b9` 验证成功：普通回归
`125 passed`，Phase 5 端到端 `6 passed`。

## 停止边界和下一步

本批次已经停止，未启动任何正式种子。审查者应重点核验：

1. P2 的 3/9/18 数量与全最优状态；
2. 冷热目标逐预算严格一致；
3. Gurobi 13.0.2、`gurobi_direct`、Threads=1 且无回退；
4. 新处置字段存在且没有补救不可行；
5. E3 `12/12` 与 family `12/12 runs、30/30 work units`；
6. E1–E5 投影量纲和 168/72 小时门槛；
7. `formal_execution_authorized=true` 没有被解释为自动执行许可；
8. PR 没有大型输出或科学代码改动。

复审通过后，下一步应由用户单独决定并明确授权正式实验的批次顺序；不得由本
PR 自动开始。
