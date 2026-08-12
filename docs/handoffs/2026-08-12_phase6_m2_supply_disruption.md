# Phase 6 M2 Supply Disruption Handoff

## 任务目标

在不改写 M0/M1 结果的前提下，实现灾害相关常规合同履约中断的最小结构扩展，并建立严格 C0 对照、共同随机数生成协议、独立复现命名空间和设计期测试。未运行任何科学实验。

## 分支和提交

- Branch: `agent/phase6-m2-supply-disruption`
- Base: PR #41 merge `1a9fa3063a18c482812b2328cb38aee5503f78d8`
- Validated implementation commits: `dae3ca1`, `3810d52`, `aefcec1`
- Draft PR: https://github.com/nieying-code/phrase3/pull/42
- Validated implementation/documentation head: `566b97d5ca40ae46b16ed969191bd06d9d994390`
- CI: [run 31561123103](https://github.com/nieying-code/phrase3/actions/runs/31561123103), Linux and Windows passed

## 修改内容

- M2 专用 `DisruptedProcurementData` 携带场景履约率，M0/M1 公共数据结构及既有指纹不变。
- M2 专用构造器用 `alpha*x` 作为常规到货，并显式报告已履约量和未履约合同量；共享求解器只在受控 M2 上下文内路由至该构造器。
- 未履约合同不退款、不入库、不处置、不损耗、不二次计费。
- 冻结的需求潜变量同时驱动需求和履约率，不增加随机抽取。
- C0 强制 `alpha=1`；C1/C2 与 C0 使用共同随机数。
- 完整扩展式、标准 C&CG、SPW-C&CG 和单场景补救共享同一模型结构。
- M2 配置、五类指纹、输出根目录与授权状态独立于 M0/M1。

## 验证范围

允许且已执行的仅为语法检查、专项单元测试和小规模算法一致性测试。禁止的27组开发矩阵、pilot、正式种子及 M0 E3均为0。专项测试 `13 passed`；完整本地回归 `252 passed`（最终接口修订后将再次确认）。

## 独立指纹

- Scientific config: `a2ac5dac56ee1e473a1397492e363eb76d330db9b9a69773b181304505784124`
- E3 component: `bb63ccda160312059179ea15446cee4f4f4db60975c47b13156d77976ffe8d67`
- Family component: `cfc69451989ad8d4771f7399f63b7a6e95fcf640516dd52564bc0fcb560300d3`
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

## 下一步

复审并手动合并后，另建 PR 冻结开发矩阵并实现安全执行器；仍需再次复审才能执行27组开发配置。
