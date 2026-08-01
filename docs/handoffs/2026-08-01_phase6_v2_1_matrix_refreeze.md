# Phase 6 v2.1 Matrix Refreeze Handoff

## 任务目标

在相对完全补救修复 PR #14 通过复审并合并后，以独立、可审计的提交把
Phase 6 精简实验矩阵 v2.1 从候选状态重新冻结。本任务只改变矩阵生命周期
状态和修订日期，不修改模型、算法、规模、预算、种子、策略或统计规则，
也不运行任何 pilot 或正式种子。

## 分支和提交

- Branch: `agent/phase6-refreeze-v2-1`
- Base branch: `main`
- Base SHA: `9aff27c24d9e04a768ec5fc434ceaed17334f168`
- Commit SHA: pending (to be filled after publication)
- Draft PR: pending (to be filled after publication)
- CI: pending (to be filled after publication)

## 修改内容

- `status`: `candidate_for_freeze_pending_review` →
  `frozen_for_formal_execution`
- `revised_on`: `2026-07-31` → `2026-08-01`
- README、实验矩阵说明、family runner说明和E3 runner说明同步为重新冻结
  后的边界。
- 矩阵状态测试更新为冻结状态；候选矩阵阻断 pilot 的专项测试仍保留。

## 指纹影响

生命周期字段不进入科学配置哈希，因此重新冻结前后必须满足：

| 指纹 | 重新冻结前 | 重新冻结后 |
|---|---|---|
| scientific config | `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3` | `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3` |
| E3 component | `7713671bab67eec8d99fdf776f1d645740d09d020ef31b55513ccc80595f951f` | `7713671bab67eec8d99fdf776f1d645740d09d020ef31b55513ccc80595f951f` |
| family component | `5803afd60d39a2e982d9b2c879453ef2d4e21755fcb46791810a1e1de8e5076f` | `5803afd60d39a2e982d9b2c879453ef2d4e21755fcb46791810a1e1de8e5076f` |

矩阵文件字节哈希会因生命周期字段变化而改变。重新冻结前的矩阵 SHA-256
为 `8acf667fff8401b1384e650f86aa25150a38980832146f789f5ad71aa2ae756d`；
重新冻结后的文件哈希为
`61de9544a4ca80a904700ddf5e12c3dd75e568c31b7d8d2bd24e76c59fabc731`。

## 执行边界

- 旧 V1、E1、E2、E4、E5 pilot 继续只作为历史诊断证据，不进入新门槛。
- 本 PR 不运行 V1、family、V2、P1、P2 pilot，也不运行正式种子。
- 本 PR 合并后，只允许按新模型、新指纹和全新 run ID 重跑 pilot。
- `formal_execution_authorized` 在完整 E3/family pilot、计算量投影与规模
  门槛通过前必须保持 `false`。
- P3、P4 继续不属于精简矩阵。

## 验证结果

```text
.venv-gurobi\Scripts\python.exe -m pytest -q
126 passed in 26.40s

.venv-gurobi\Scripts\python.exe -m compileall -q src tests
通过

git diff --check
通过（仅 Windows LF/CRLF 提示）
```

Gurobi/gurobipy 仍严格为 13.0.2，Pyomo 接口为 `gurobi_direct`，
`Threads=1`。本次没有调用任何实验 runner。

## 下一步建议

本 Draft PR 通过 ChatGPT 复审并由用户手动合并后，先按受审顺序重跑
当前指纹 pilot；完成后立即停止并提交独立结果 PR，不得直接启动正式种子。

## ChatGPT 审查清单

1. 矩阵本体是否只修改 `status` 和 `revised_on`。
2. 科学配置、E3 和 family 三类指纹是否保持不变。
3. 候选状态阻断 pilot 的代码与测试是否仍然存在。
4. 冻结状态是否只允许 pilot，而未绕过正式投影和规模推进门槛。
5. 是否没有运行或提交任何新实验结果。
