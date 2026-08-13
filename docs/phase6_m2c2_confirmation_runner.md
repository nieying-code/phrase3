# Phase 6 M2C2 双物资确认安全执行器

本修订将已复审的30组双物资确认设计冻结为 `frozen_for_confirmation_execution`，并实现独立 runner；本修订本身不运行矩阵。

## 冻结身份

- 档位：`M2C2`，2物资、6期、50训练场景；
- 种子：`2026081301–2026081305`；
- 预算：`beta=1.1/1.3`；
- 档位：`C0/C1/T03`；
- 严格顺序：seed → beta → C0/C1/T03，共30组；
- 输出：`outputs/phase6_m2c2_confirmation_v1_0`，不读取旧轨道 registry/projection 作为授权。

执行前必须同时满足冻结状态、审批文件五类指纹及显式 `--authorize-confirmation-execution`。Primary 只能从空输出根目录完整运行30组；诊断重试只能携带单一 case 与既有失败 primary 的 `parent_run_id`。

## 科学阶段

每组依次执行双物资预算/容量复算、场景生成、最低可行储备、完整扩展式、完整扩展式容差最优储备区间、两个端点的50场景精确补救，以及四种固定储备策略。跨物资指标只使用 `R_min_opt` 端点方案。

C0还必须完成双向等价验收：无中断模型和M2 C0的鲁棒目标、储备区间，以及双方固定第一阶段方案在另一模型上的50场景精确补救均须在冻结容差内一致。C0储备为零本身不能替代该验收。

## Projection

Projection重新核算科学数值、固定自主储备公式、CRN（含场景顺序）、C0等价和跨物资支出，不信任保存的门槛布尔值。每个预算独立通过后才进入 `passing_betas`：仅一个预算通过时禁止预算效应结论；两个均通过时才允许预算调节比较。无论结果如何，runner始终输出 `formal_extension_authorized=false`。

## 停止边界

本PR只允许单元、mock和小型一致性测试。禁止使用显式授权参数运行30组，禁止pilot、正式扩展和M0 E3。
