# Phase 6 M1 Development Runner Handoff

## 任务目标

在 PR #39 的 M1 采购能力扩展模型基础上，冻结 63 组 V1 开发矩阵并实现独立、安全、可审计的串行执行器。本任务只交付执行基础设施，不运行任何开发配置、pilot、正式种子或 M0 E3。

## 分支和提交

- Branch：`agent/phase6-m1-development-runner`
- Base branch：`main`
- PR #39 merge/base：`cf6847c9d25574bb70be73d9d96b81a875a52b93`
- Commit SHA：`pending`
- Draft PR：`pending`
- CI：`pending`

## 修改内容

### 冻结协议

- M1 状态更新为 `frozen_for_development_execution`。
- 科学网格保持 V1、3 个开发种子、3 档 beta 和 7 档 kappa，共 63 组；无上限仍严格编码为 `enabled=false, kappa=null`。
- 科学配置指纹保持 PR #39 的 `6439d8a...`；执行器加入 M1 E3/family 组件保护范围后，组件和 runner 指纹按设计更新。

### 开发执行器

- 每个配置严格串行完成最低可行储备、完整扩展式最优目标、完整扩展式最优面两端、端点精确补救重评和四个固定自主储备策略。
- 真实调用继承冻结 V1 单次 solver 时限，只允许 Gurobi 13.0.2、`gurobi_direct`、`Threads=1`。
- 结果包括储备分解、激活判据、端点一致性、策略采购哈希、失败计数、阶段时间和峰值内存。

### 安全与复现

- 冻结状态和显式 `--authorize-development-execution` 构成双重门槛，且在场景生成前验证。
- 独立 M1 输出根目录和批准指纹；拒绝 M0 registry、projection 或授权。
- run ID 终态及中断 checkpoint 均不可覆盖；诊断重试必须新 ID 加 `parent_run_id`。
- status summary/heartbeat 保持小型；状态工具不读取大型 result/checkpoint。
- result、manifest、registry、projection 按顺序最终化，并使用跨进程锁。

### 机器门槛

- 同一 beta-kappa 组合必须 3/3 optimal 且至少 2/3 达到 1% 实质自主激活。
- 成本、服务水平、P95、CVaR 和人工趋势被明确排除。
- 无组合通过时自动停止参数追逐；有组合通过也保持 `formal_extension_authorized=false`。

## 指纹

- Scientific：`6439d8a1945e44985cb1c8b20a20b7641617ed9a160db554680f3dc4680aa8c8`
- E3 component：`4028461ade600cf6cf8db68cba8e1360fe7dcc838edffd0173aa4c98bbdf112c`
- Family component：`a39f24b2ef213a7e5dba860e375751c46c15aafb13a11d28b2ab8f295f5ff5e6`
- Runner config：`4e39efe184877da9892e63852298bad4f9662b6d09af7ef5fedd6c4a09a13f3a`
- Environment：`b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`

## 验证结果

- M1 runner专项测试：`25 passed in 23.69s`
- 完整回归：`217 passed in 61.06s`；CI拆分为 `211 passed in 57.27s + 6 passed in 7.33s`
- Windows复现专项：`16 passed in 8.17s`
- 语法检查：通过
- `git diff --check`：通过
- GitHub Actions：`pending`

## 明确未执行

- 63 组 M1 开发配置：`0`
- M1 pilot：`0`
- M1 正式运行：`0`
- M0 E3：`0`

## 已知限制和停止边界

本 PR 只冻结和实现开发执行器，不提供 M1 正式扩展实验授权。Draft PR 完成后停止；未经用户在合并后另行明确授权，不得使用 CLI 授权参数运行矩阵。

## ChatGPT 审查清单

1. 63 组笛卡尔积及无上限编码是否精确；
2. 场景生成前双重门槛和五类指纹是否完整；
3. 最优储备区间是否始终来自完整扩展式；
4. 两端点是否逐场景精确重评；
5. 四个固定策略是否分别重优化采购；
6. 失败、中断、成功 run ID 是否不可覆盖；
7. registry/projection 是否能抵抗多进程覆盖；
8. 3/3 与至少 2/3 门槛是否完全机器化；
9. formal authorization 是否始终为 false；
10. 是否确实没有运行任何实验。
