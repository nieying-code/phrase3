# Phase 6 M2.1 小型 pilot runner 冻结交接（v1.0）

## 结论与边界

本 PR 在 PR #62 合并基线 `770c863d69ba37ba858b00931310f94a9fb84e77` 上实现 M2.1 科学 runner，冻结三组训练—验证—测试种子三元组，但不授权执行。当前：

- pilot primary run：0；
- 场景生成：0；
- Gurobi 调用：0；
- 正式 M2.1 run：0；
- M0 E3 与算法性能 run：0。

`configs/phase6_m2_1_pilot.yaml` 已冻结科学顺序，但其中 `pilot_authorized=false`；审批文件同样为 `runner_review_pending/pilot_authorized=false`。未来必须通过独立受审授权 PR 同时更新两层门槛和指纹，当前分支无法执行科学任务。

## 冻结 pilot

三个不可拆分 primary run 严格串行：

| 位置 | 训练种子 | 验证种子 | 测试种子 | 测试探针 |
|---:|---:|---:|---:|:---:|
| 1 | 2026090401 | 2026090501 | 2026090701 | 是 |
| 2 | 2026090402 | 2026090502 | 2026090702 | 否 |
| 3 | 2026090403 | 2026090503 | 2026090703 | 否 |

每个run依次执行：100个训练场景上的完整扩展式最优目标与容差最优储备区间、三候选采购重新优化、一个共享2000场景验证集上的三候选评价及冻结选择。第一组三元组再在一个共享2000场景测试集上运行六种策略探针。

闭合计数：

- 3个训练区间run；
- 9个验证候选方案、18,000次精确补救评价；
- 6个测试探针方案、12,000次精确补救评价。

## 身份与选择门槛

- 每组三候选只生成一次验证场景；7类场景身份和场景顺序必须完全一致。
- 六种测试策略只生成一次测试场景；同样锁定7类身份。
- `minimum_endpoint`只最终化一次，同时作为M2控制方案。
- 验证结果逐项绑定最终方案哈希、采购哈希、储备、训练目标及训练场景哈希。
- M2.1选择严格由验证集CVaR95、均值成本、储备量的冻结顺序机械复算；测试集不能选择方案。
- 若选择最小端点，M2.1与M2共享同一方案对象和最终制品，探针差异必须在冻结容差内为零。

## 执行安全

- 新namespace与空输出根：`outputs/phase6_m2_1_endpoint_selection_pilot_v1_0`；
- primary必须一次运行完整3条，禁止任意子集；
- diagnostic必须绑定同case既有失败primary，并使用新run ID；
- run ID和成功、失败、超时、中断终态不可覆盖；
- result→manifest→registry→projection顺序最终化，registry/projection使用跨进程锁；
- 小型status工具只读取不超过16 KiB的`status_summary.json`，不解析大型result/checkpoint；
- 任一失败、超时、身份不一致或最终化失败停止后续case；
- projection即使通过也始终保持`formal_extension_authorized=false`。

## 五类指纹

- scientific config：`91e20926b71287e61ea0adcd95c4f6c2f67c452c678c2a7bd380c02c27515c71`
- E3 component：`ec5545db03791d053b14942fa02f94215a2d3711634c90a747fec6e9e5dfe618`
- family component：`3807bffa3e301656a818a80a5942439ed6bd1b2ece9812b47be661b29758f071`
- runner config：`b0f975506ac5de4262987f40bbee50af60b9343730fff9a37139dc7068ed8bc2`
- environment：`b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`

CI与最终提交记录在PR正文，避免审计文件自引用。完成本PR后停止；不得运行pilot或正式实验。
