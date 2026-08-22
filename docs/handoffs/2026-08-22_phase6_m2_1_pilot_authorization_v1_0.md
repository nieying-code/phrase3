# Phase 6 M2.1 小型 pilot 授权交接（v1.0）

## 授权范围

本 PR 基于 PR #63 合并提交 `662f8b65aa7b42ab997badee37f1ed25ccc014d4`，只开放已经受审的三组三元组技术 pilot。科学矩阵、runner、求解器限制、停止规则和输出命名空间均未改变。

授权后的 pilot 必须一次严格串行运行完整三组：

- `2026090401 / 2026090501 / 2026090701`，包含六策略测试探针；
- `2026090402 / 2026090502 / 2026090702`；
- `2026090403 / 2026090503 / 2026090703`。

闭合工作量仍为9个验证候选、18,000次验证补救评价，以及6个独立测试策略、12,000次测试补救评价。

## 双重门槛

- 协议：`execution_boundaries.pilot_authorized=true`；
- 审批：`status=approved_for_pilot_execution`且`pilot_authorized=true`；
- CLI仍必须显式提供`--authorize-pilot-execution`；
- 实际运行前继续严格核验Git源码、五类指纹、Python 3.12.10、Gurobi/gurobipy 13.0.2、`gurobi_direct`和`Threads=1`。

## 保持关闭的范围

以下字段全部保持`false`：正式训练、正式验证、选择方案冻结、正式测试、正式扩展及继承M2授权。即使pilot机器门槛通过，也只能创建独立的后续冻结PR，不能自动运行正式M2.1实验。

本授权PR中的场景生成、Gurobi调用、pilot运行、正式运行、算法性能运行和M0 E3运行数均为0。CI及最终提交记录在PR正文中。
