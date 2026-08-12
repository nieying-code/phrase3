# Phase 6 M2 Supply Disruption Handoff

## 任务目标

在不改写 M0/M1 结果的前提下，实现灾害相关常规合同履约中断的最小结构扩展，并建立严格 C0 对照、共同随机数生成协议、独立复现命名空间和设计期测试。未运行任何科学实验。

## 分支和提交

- Branch: `agent/phase6-m2-supply-disruption`
- Base: PR #41 merge `1a9fa3063a18c482812b2328cb38aee5503f78d8`
- Intermediate implementation commits: `dae3ca1`, `3810d52`, `aefcec1`
- Draft PR: https://github.com/nieying-code/phrase3/pull/42
- Intermediate documentation head: `566b97d5ca40ae46b16ed969191bd06d9d994390`
- Intermediate CI: [run 31561123103](https://github.com/nieying-code/phrase3/actions/runs/31561123103), Linux and Windows passed
- Final scientifically reviewed head: `aad5d3c7ad0fa344b17ffe1f4a75542b6acf4cf3`
- Final scientifically reviewed CI: [run 31565293591](https://github.com/nieying-code/phrase3/actions/runs/31565293591), Linux and Windows passed
- Final local validation at the reviewed head: M2 focused suite `20 passed`; full regression `259 passed`
- Traceability-only synchronization after the reviewed head changes no model, algorithm, configuration, fingerprint, or experiment result; its final commit and CI are recorded in the PR description to avoid a self-referential SHA update loop.

## 修改内容

- M2 专用 `DisruptedProcurementData` 携带场景履约率，M0/M1 公共数据结构及既有指纹不变。
- M2 专用构造器用 `alpha*x` 作为常规到货，并显式报告已履约量和未履约合同量；共享求解器只在受控 M2 上下文内路由至该构造器。
- 未履约合同不退款、不入库、不处置、不损耗、不二次计费。
- 冻结的需求潜变量同时驱动需求和履约率，不增加随机抽取。
- C0 强制 `alpha=1`；C1/C2 与 C0 使用共同随机数。
- 完整扩展式、标准 C&CG、SPW-C&CG 和单场景补救共享同一模型结构。
- M2 配置、五类指纹、输出根目录与授权状态独立于 M0/M1。
- 开发种子改为全新 `2026081201/02/03`，与M1开发轨道隔离。
- 联合场景身份覆盖潜变量、需求、履约、应急价格、应急供应和整条联合记录，并贯穿全部算法证据。
- 履约统计分别处理零需求、常量需求、常量履约及有效样本不足。
- C0验收增加完整储备区间和双向固定精确补救重评。
- M2上下文增加可重入锁，并验证异常后全部构造器恢复。

## 验证范围

允许且已执行的仅为语法检查、专项单元测试和小规模算法一致性测试。禁止的27组开发矩阵、pilot、正式种子及 M0 E3均为0。复审修复专项测试 `20 passed`；完整本地回归 `259 passed`。

## 独立指纹

- Scientific config: `c354a91917c31ed51429d6b2e84a8b2c09dcefcc1ad145a58ef0f27e0e87742d`
- E3 component: `f4db040c9d62965e1c90f38d091a0b519b226e565c93c6c2972ce6263dec7f38`
- Family component: `d6b623cf16108681f263efc4f12f9961fa986833d24e2ca91d78959b09001f9d`
- Runner config: `d9de25037d85b21e4cc086b73db29a1eb9d6c95066154001c0463de12d66eb10`
- Environment: `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`

## 风险点与审查重点

1. C0 是否逐元素严格等于1并恢复 M0。
2. 合同成本是否仍按全额采购计入预算且没有退款/重复成本。
3. 未履约合同是否完全排除在库存、处置和到期损耗之外。
4. 需求和履约是否共享冻结潜变量且没有改变 M0 随机抽取顺序。
5. 完整扩展式、补救、C&CG与SPW-C&CG是否共享公共约束。
6. 最优储备区间是否基于完整扩展式而非受限主问题。
7. M2是否错误继承M0/M1授权或制品。
8. 联合场景身份是否对科学分量敏感并贯穿所有算法证据。
9. 统计未定义状态和上下文异常恢复是否完整。

## 下一步

复审并手动合并后，另建 PR 冻结开发矩阵并实现安全执行器；仍需再次复审才能执行27组开发配置。
