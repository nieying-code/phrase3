# Phase 6 Relative Complete Recourse Fix Handoff

## 任务目标

诊断三个 E4 pilot 中出现的样本外补救不可行，只有在 Gurobi IIS 确认
根因后，才对公共库存模型实施最小的有惩罚提前处置修复，并证明相对完全
补救。本任务不运行任何 Phase 6 pilot 或正式种子。

## 分支和提交

- Branch: `fix/phase6-relative-complete-recourse`
- Base branch: `main`
- Base SHA: `5abb3f907b001871c03ab9e783a33a09f99ab6f6`
- Model/test commit SHA: `70a68ea671a9cf94e0c01671a7b20a1cc83dc9e3`
- Validated remote head before this handoff-only update:
  `b3917739fe9ef29e0fb86e2d4b4250f23741905f`
- Draft PR: https://github.com/nieying-code/phrase3/pull/14
- CI: https://github.com/nieying-code/phrase3/actions/runs/30603204207
  (`115 passed` ordinary regression + `6 passed` Phase 5)
- PR #13: 保持 Draft，未修改、未合并

## IIS 诊断结论

从三个 E4 run 各选择一个真实不可行场景：

| Pilot seed | Test seed | Scenario | 原 run 不可行数 |
|---:|---:|---|---:|
| 2026072001 | 2036072001 | `s0028` | 60 |
| 2026072002 | 2036072002 | `s0113` | 40 |
| 2026072003 | 2036072003 | `s0014` | 93 |

三者在 Gurobi 13.0.2 中均得到原始终止条件 `infeasible`，且最小 IIS
共同包含 `available_balance`、非最大库龄 `age_flow`、
`demand_balance`、`storage_capacity` 及相关非负变量边界。第一阶段
固定采购在低需求下产生未到期剩余库存，旧模型没有提前退出通道，结转
库存因而超过期末容量。

没有证据指向超时、求解器失败、`infeasible_or_unbounded`、预算实现、
服务约束或索引错误。详细名称、哈希和 `.ilp` 路径见：

- `docs/handoffs/2026-07-30_phase6_recourse_iis_diagnosis.md`
- `docs/handoffs/2026-07-30_phase6_recourse_iis_audit.json`
- `docs/handoffs/phase6_recourse_iis/`

## 模型修改

对所有非最大库龄增加：

```text
early_disposal[scenario,item,period,age] >= 0
```

库存流转改为：

```text
available = consume + ending_inventory + early_disposal
```

最大库龄仍满足：

```text
available = consume + expired_waste
ending_inventory = 0
```

定义：

```text
total_disposal = expired_waste + sum(early_disposal over nonmaximum ages)
```

提前处置和到期损耗都使用已有且现在强制为正的
`waste_penalty[item]`。没有 Big-M、免费丢弃或条件性删除场景。
兼容字段 `waste` 明确定义为 `total_disposal` 的别名；新结果另外输出
`expired_waste`、`early_disposal` 和 `total_disposal`。

第一阶段总预算等式、应急储备含义、应急采购预算、C&CG/SPW-C&CG
oracle、上下界、终止条件和场景池逻辑均未改变。

## 相对完全补救

对任意非负有限需求和任意满足第一阶段预算的采购/储备方案，可令：

- 应急采购与消费为 0；
- 缺货等于需求；
- 期末库存为 0；
- 非最大库龄全部进入 `early_disposal`；
- 最大库龄全部进入 `expired_waste`。

此时应急支出和仓储占用均为 0，分别不超过储备金和任意非负容量，所有
流量平衡成立。因此第二阶段至少有一个可行解。代码仍保留
`infeasible`、`infeasible_or_unbounded`、超时和求解失败的严格分类，
便于发现未来模型或数据异常。

## 版本与指纹

实验矩阵由 `2.0` / `phase6_streamlined_experiments_v2_0` 升级为
`2.1` / `phase6_streamlined_experiments_v2_1`，状态恢复为
`candidate_for_freeze_pending_review`。

| 指纹 | 旧值 | 新值 |
|---|---|---|
| scientific config | `3ac92ff09d85eebd99ba42dfaae54fb4b1ce7171d8e8a5f1bf8bceddb4524745` | `8393c0543c5b9fee3369d0cf836821d6f5ae29c38ecede8f18b27391b6573289` |
| E3 component | `bce43075dd91053b5b2c4fa2942fa84bea02654be17d2f10c99df08176248342` | `260c7bb2f8062954460a9436def8f70f9d80f6ef4f7848d64781730848de39e5` |
| family component | `fb96854f96c13a3788548c78a0ac0cd1ca6b168cb5f21f74f334ca9b13ca5006` | `87f592f26a47775907dd689342d510e4d501a849116670e8e0c025d51a8c3a00` |

旧 V1 E3 pilot 和旧 E1/E2/E4/E5 family pilot 全部保留为历史诊断
证据，但不能进入新门槛。旧 run 没有被删除或覆盖；后续重跑必须使用
新 run ID。

## 结果影响

- 阶段 1–2：开发模型语义和测试基线已同步；无需恢复旧数值快照。
- 阶段 3–4：算法结构不变，扩展式和标准 C&CG 需要按新模型重新验收；
  本分支已完成获准的小规模快速验收。
- 阶段 5：SPW-C&CG 逻辑不变，六预算冷热一致性需要按新模型重新验收；
  本分支已完成获准的快速验收。
- Phase 6：所有旧 E3 与 family pilot 数值结果对新科学模型失效；修复
  PR 合并并重新冻结后，V1 及 family pilot 必须使用全新 run ID 重跑。
  V2、P1、P2 和正式种子仍未获准。

## 验证结果

唯一解释器：

```text
D:\新建文件夹\项目交付\阶段3-4修复同步\phrase3\.venv-gurobi\Scripts\python.exe
```

环境为 Gurobi Optimizer 13.0.2、gurobipy 13.0.2、
`gurobi_direct`、`Threads=1`，无 HiGHS 回退。

实际命令与结果：

```text
python -m pytest -q
121 passed in 27.25s

python -m compileall -q src tests
通过

python -m src.run_phase3 --config configs/phase3.yaml
extensive = 3128.747644544431
standard C&CG = 3128.747644544431
difference = 0
iterations = 1
acceptance = passed

python -m src.run_phase5 --config configs/phase5.yaml
status = optimal
budgets = 700,800,900,1000,1100,1200
max cold/warm objective difference = 0
total iteration reduction = 3

git diff --check
通过（仅 Windows LF/CRLF 提示）
```

没有运行新 V1、family pilot、V2、P1、P2 或任何正式种子。

## 主要修改文件

- `src/model_common.py`：公共库存平衡、处置变量与成本。
- `src/model_data.py`：要求处置惩罚严格为正。
- `src/recourse_model.py`、`src/inventory_model.py`：显式结果字段。
- `src/phase6_families.py`、`src/run_phase3.py`：E4/CSV 指标。
- `configs/phase6_experiment_matrix.yaml`：v2.1 候选矩阵及退出协议。
- `tests/test_relative_complete_recourse.py`：结构可行性专项回归。
- `docs/mathematical_model.md`：符号、方程、成本和构造性证明。

## 已知限制与风险点

- `early_disposal` 聚合表示提前报废、捐赠、跨区调出等多类渠道，尚未
  用真实数据拆分渠道或校准不同处置成本。
- 为避免新增任意参数，提前处置沿用到期损耗惩罚；应在论文中作为明确
  假设，并在 E5 做惩罚敏感性解释。
- 连续 LP 仍不强制严格二进制 FIFO。
- 本次不提供新 Phase 6 性能结论。

## ChatGPT 审查清单

1. IIS 是否足以支持“未到期库存缺少出口”的根因判断；
2. 非最大库龄和最大库龄是否互斥进入两类处置；
3. `total_disposal` 是否只求和一次并正确进入成本；
4. `waste` 兼容字段是否在所有输出中都明确为总退出量；
5. 构造性相对完全补救证明是否覆盖保质期 1、多物资和多期；
6. 第一阶段预算和应急储备含义是否保持不变；
7. C&CG/SPW-C&CG 算法逻辑是否未被修改；
8. 旧 pilot 是否确实被三类新指纹排除；
9. 矩阵是否正确恢复候选状态；
10. 测试是否覆盖状态分类、序列化和 CSV/E4 字段。

## 下一步

等待 ChatGPT 复审和用户手动合并。合并后先通过独立受审提交重新冻结
矩阵，再制定全新 run ID 的 Phase 6 pilot 重跑顺序；不得在本 PR 中
启动后续实验。
