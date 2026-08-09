# Phase 6 Final Projection Reaggregation Handoff

## 任务目标

在 PR #32 合并后的已批准 E3 12/12 与 family 12/12 制品基础上，只读核验既有制品并执行一次最终 family 投影重汇总。不得生成场景、调用 Gurobi 求解或启动正式种子。

## 分支和提交

- Branch: `agent/phase6-final-projection-repro-v4`
- Base / execution commit: `f91e10c9140fc49b4a67dcaadc654a8bfb9df8e3`
- Execution tree: `e3ed562c3a63cb45309f86e8a681f4cd6acea000`
- Results documentation commit: pending
- Draft PR: pending
- CI: pending

## 执行内容

1. 验证矩阵状态为 `frozen_for_formal_execution`。
2. 验证科学、E3、family、runner 与环境指纹。
3. 重新校验 12 条 family primary 的 result/manifest 哈希，未发现制品错误。
4. 仅读取现有 E3 与 family registry、projection 和最终制品。
5. 原子重写 `pilot_throughput_projection.json`，没有创建任何新 run。
6. 独立复算五个实验族预计工时和完整机器门槛。

## 投影结果

| 实验族 | 正式工作量 | 保守吞吐率 | 预计墙钟时间（h） |
|---|---:|---:|---:|
| E1 | 45 work units | 1456.017120 work units/h | 0.0309062300 |
| E2 | 180 work units | 1365.023414 work units/h | 0.1318658700 |
| E3 | 519000 recourse LP | 58516.742726 LP/h | 8.8692564867 |
| E4 | 90 work units | 118.063150 work units/h | 0.7623039050 |
| E5 | 75 work units | 1626.855443 work units/h | 0.0461012073 |

- 五族总预计时间：`9.840433698969827 h`，低于 `168 h`。
- 最大单族：E3，`8.86925648667795 h`，低于 `72 h`。
- E3：`12/12` primary，缺失、失败、无效、重复和诊断均为 0。
- Family：`12/12` primary，`30/30` 工作单元，非最优为 0。
- Projection status: `passed`
- `compute_gate_passed=true`
- `formal_execution_authorized=true`

`formal_execution_authorized=true` 仅表示机器门槛通过，不是自动运行许可。本任务完成后仍停止，必须等待 ChatGPT 复审、用户手动合并以及用户另行明确授权第一个正式实验批次。

## 制品追溯

- Projection 重汇总前 SHA-256：`ca5bea5f4e2a5876d3a76cf4778f92439097ac0c9f9a16ba9b666eaa351f33eb`
- Projection 重汇总后 SHA-256：`c3b9c26e69a46aa89a99d7b6f40ff307c308c2782405e884154bc21c906faff2`
- E3 registry SHA-256：`3a46e655fbeca18f730f755c2d38a9ebdfc6946be4ef7a9ba9576535975a4fe9`
- Algorithm performance SHA-256：`2486b070ee569bcc938cdb2468eb173d658353fd181c286bdaccf6216cb791c3`
- Family registry SHA-256：`fc9051452d8eafbd7bcbc871f38936b7206554499db054b0c4596bc94e9958b9`
- 紧凑机器审计：`docs/handoffs/2026-08-09_phase6_final_projection_reaggregation_audit.json`

## 验证结果

- 专项审计测试：`python -m pytest tests/test_phase6_final_projection_reaggregation_audit.py -q`，`1 passed in 0.06s`
- 完整回归：`python -m pytest -q`，`164 passed in 38.82s`
- 语法检查：`python -m compileall -q src tests`，通过
- `git diff --check`：通过
- GitHub Actions：pending

## 停止边界

- 未生成任何新场景。
- 未调用 Gurobi 求解。
- 未创建新 pilot 或 development run。
- 未启动 E1、E2、E3、E4、E5 任何正式种子。

## 下一步建议

ChatGPT 复审本 PR，用户手动合并后，用户需另行明确批准第一个正式实验批次、运行顺序和停止边界。不得把本次机器授权解释为自动启动许可。

## ChatGPT 审查清单

1. 五个实验族的工时是否可由工作量除以保守吞吐率独立复算；
2. 五族总时间与最大单族时间是否满足 `168/72 h` 门槛；
3. E3 是否为 `12/12` 且所有异常集合为空；
4. family 是否为 `12/12 runs`、`30/30 work units` 且全部最优；
5. 四个全局制品及重汇总前后 projection 哈希是否锁定；
6. `formal_execution_authorized=true` 是否仍明确要求人工授权；
7. 本任务是否没有生成场景、调用求解器或启动正式种子。
