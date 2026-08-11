# Phase 6 M1 Development Runner Handoff

## 任务目标

在 PR #39 的 M1 采购能力扩展模型基础上，冻结 63 组 V1 开发矩阵并实现独立、安全、可审计的串行执行器。本任务只交付执行基础设施，不运行任何开发配置、pilot、正式种子或 M0 E3。

## 分支和提交

- Branch：`agent/phase6-m1-development-runner`
- Base branch：`main`
- PR #39 merge/base：`cf6847c9d25574bb70be73d9d96b81a875a52b93`
- Draft PR：https://github.com/nieying-code/phrase3/pull/40
- 最终修复提交和 CI：发布后更新

## 修改内容

### 冻结协议

- M1 状态为 `frozen_for_development_execution`。
- 科学网格保持 V1、3 个开发种子、3 档 beta 和 7 档 kappa，共 63 组；无上限严格编码为 `enabled=false, kappa=null`。
- 科学配置指纹保持 PR #39 的 `6439d8a...`；runner 安全修复按设计更新 M1 E3/family 组件指纹。

### 开发执行器

- 每个配置严格串行完成最低可行储备、完整扩展式最优目标、完整扩展式最优面两端、端点精确补救重评和四个固定自主储备策略。
- 所有科学求解阶段继承冻结 V1 单次 solver 时限 `120` 秒，只允许 Gurobi 13.0.2、`gurobi_direct`、`Threads=1`。
- 原生 `time_limit`、`master_time_limit` 和嵌套补救超时统一进入不可变 `timeout` 终态，并保留原始求解状态和失败阶段。
- 结果包括储备分解、激活判据、端点一致性、策略采购哈希、失败计数、阶段时间和后台采样得到的进程 RSS 峰值。

### 安全与复现

- 冻结状态和显式 `--authorize-development-execution` 构成双重门槛，且在场景生成前验证。
- 批准文件的 ID、状态、协议、namespace、63组计数、显式授权、正式实验禁用及M0隔离字段均精确校验。
- 独立 M1 输出根目录和批准指纹；拒绝 M0 registry、projection 或授权。
- run ID 只允许安全字符并执行受控根目录检查；状态读取使用相同规则。
- 成功、失败、超时、中断和 runner 异常均形成不可变终态；诊断重试必须新 ID 加 `parent_run_id`。
- 矩阵加载、科学求解、环境提取、manifest和registry最终化纳入统一生命周期。
- status summary/heartbeat 保持小型；状态工具不读取大型 result/checkpoint。
- result、manifest、registry、projection 按顺序最终化，并使用跨进程锁。
- `peak_memory_mb` 的语义锁定为后台轻量采样器得到的 `sampled_process_peak_rss_mb`。

### 机器门槛

- 同一 beta-kappa 组合必须 3/3 optimal 且至少 2/3 达到 1% 实质自主激活。
- 成本、服务水平、P95、CVaR 和人工趋势被明确排除。
- 无组合通过时自动停止参数追逐；有组合通过也保持 `formal_extension_authorized=false`。

## 指纹

- Scientific：`6439d8a1945e44985cb1c8b20a20b7641617ed9a160db554680f3dc4680aa8c8`
- E3 component：`994e72479f0994c134d112bef1af78421ee3cca25593ab6a9d1146e153afbde2`
- Family component：`05065fba9dd69665bf556da2e6b44fde7e0f73d476172811aeb4d662b74a839d`
- Runner config：`4e39efe184877da9892e63852298bad4f9662b6d09af7ef5fedd6c4a09a13f3a`
- Environment：`b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`

环境指纹锁定本地受控 Gurobi 执行主机；跨平台 CI 只验证其记录和格式，不要求托管机与本地主机哈希相同。未来真实 M1 开发运行必须匹配上述本地批准值。

## 验证结果

- M1 runner 专项测试：`45 passed in 24.50s`
- 完整回归：`237 passed in 66.18s`
- CI 拆分本地复现：`231 passed in 54.88s + 6 passed in 6.08s`
- Windows 复现专项：`16 passed in 7.88s`
- 语法检查：通过
- `git diff --check`：通过
- GitHub Actions：runner 加固提交发布后更新

## 明确未执行

- 63 组 M1 开发配置：`0`
- M1 pilot：`0`
- M1 正式运行：`0`
- M0 E3：`0`

## 已知限制和停止边界

本 PR 只冻结和实现开发执行器，不提供 M1 正式扩展实验授权。Draft PR 修复后继续停止；未经复审、用户手动合并及另行明确授权，不得使用 CLI 授权参数运行矩阵。

## ChatGPT 审查清单

1. 完整扩展式和其余阶段是否均使用120秒冻结时限；
2. 原生及嵌套求解超时是否统一形成 `timeout` 终态；
3. 矩阵加载、环境提取和制品最终化失败是否形成可追踪终态；
4. run ID及状态读取是否阻止路径穿越；
5. 内存字段是否确实来自后台RSS采样；
6. 批准文件关键元数据是否精确校验；
7. 最优储备区间是否始终来自完整扩展式且端点逐场景重评；
8. 3/3 与至少 2/3 门槛是否完全机器化；
9. formal authorization 是否始终为 false；
10. 是否确实没有运行任何实验。
