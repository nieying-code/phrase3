# Phase 6 M2 Generated-Wrapper Fix Handoff

## 根因

首次M2开发执行在首个C0配置的场景生成后停止。`generate_m2_data()`返回`GeneratedM2Data`包装对象，而runner错误地直接读取`generated.tier`；当时包装对象只公开`data`，导致`AttributeError`。失败发生在任何Gurobi调用之前。

## 修复

- runner显式从`generated.generated.tier`读取冻结的120秒求解时限；
- `GeneratedM2Data`增加只读协议元数据代理，封闭包装接口；
- 新增真实M2生成对象测试，使用50个V1场景执行到首个求解阶段并在mock边界停止；
- 协议、runner namespace与输出根目录升级为`v1_1`，不读取或覆盖旧`v1`失败制品；
- 旧run `m2dev_v1_20260812_V1_seed2026081201_beta0p90_profileC0`永久保留为不可变失败证据。

## 新执行身份

- Protocol: `phase6_m2_supply_disruption_v1_1`
- Namespace: `phase6_m2_supply_disruption_v1_1`
- Output root: `outputs/phase6_m2_supply_disruption_v1_1`
- Scientific: `9c552774ade43ceaa906b2e24fa2559a802108fa42a7ff65ca70977f054e8e48`
- E3: `3d3b29d6dba5b191a5cc8c2f660c789bafcf33cc192e4b45f34724aca0336cf5`
- Family: `455cd02cf8afbc6ce9e93a222cd320182da1ea37f65f0ea7962f4496820cd87a`
- Runner: `83a045e44149e7a899a3549c6f3d49a0a002e3230841efbaace7edef1034ae8c`
- Environment: `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`

## 边界

本修复PR没有运行任何新开发配置、pilot、正式实验或M0 E3。合并并重新授权后必须使用全新run ID前缀和新的`v1_1`输出根目录重新开始27组矩阵。
