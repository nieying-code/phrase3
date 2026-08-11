# Phase 6 M1 开发执行器

## 1. 目的与边界

`src.run_phase6_m1_development` 只执行已经冻结的 63 组 M1 V1 开发配置。它不接受 M0 的 registry、projection 或正式授权，也永远不会授权 M1 正式扩展实验。

本执行器 PR 只交付代码、配置、测试和协议，没有运行开发矩阵、pilot、正式种子或 M0 E3。

## 2. 双重执行门槛

运行必须同时具备：

1. `configs/phase6_m1_procurement_cap.yaml` 的状态为 `frozen_for_development_execution`；
2. CLI 显式参数 `--authorize-development-execution`。

预检还会在场景生成前核验 Python 3.12.10、Gurobi/gurobipy 13.0.2、`gurobi_direct`、`Threads=1`、精确依赖锁、五类批准指纹、Git tree及全部执行输入均已跟踪且无修改。

未经用户后续明确授权，不得运行以下示例。获准后应使用唯一前缀并严格串行：

```powershell
& .\.venv-gurobi\Scripts\python.exe -m src.run_phase6_m1_development `
  --run-id-prefix <new-unique-prefix> `
  --authorize-development-execution
```

`--case-id` 可限制到已冻结的具体配置；未知配置会被拒绝。诊断重试必须使用新 `run-id-prefix` 并提供 `--parent-run-id`。

## 3. 单配置阶段

每个配置按固定顺序执行：场景生成、最低可行储备 LP、完整扩展式最优目标、完整扩展式容差最优面最小/最大储备、两个端点逐场景精确补救重评，以及四个固定自主储备策略的独立采购重优化。

阶段进度原子写入 `checkpoint.json`、`status_summary.json` 和 `heartbeat.json`。状态工具只读取小型摘要或 projection，不解析大型 result/checkpoint：

```powershell
& .\.venv-gurobi\Scripts\python.exe -m src.phase6_m1_status `
  --output-root outputs/phase6_m1_procurement_cap_v1 `
  --run-id <run-id>
```

## 4. 最终化与不可变性

终态按 `result → manifest → registry → projection` 顺序写入。manifest 锁定 result、checkpoint、status summary 和 heartbeat 的 SHA-256。任何已有 checkpoint、成功、失败或超时 run 目录均不可用相同 run ID 覆盖。

registry、projection 和整批串行执行均使用跨进程文件锁。一个配置完全最终化后才进入下一配置；首次非最优状态会停止后续配置。

## 5. 开发激活门槛

每个 `beta-kappa` 组合必须 3/3 开发种子全部最优、端点精确评价完整、无失败/超时/无效/重复 primary，且至少 2/3 种子的稳健自主储备比例达到 1%。成本、服务水平、P95、CVaR 和人工趋势不参与选择。

没有组合通过时输出 `stop_reason=no_preregistered_combination_passed`。有组合通过时也只输出 `development_activation_gate_passed=true`，同时强制 `formal_extension_authorized=false`。
