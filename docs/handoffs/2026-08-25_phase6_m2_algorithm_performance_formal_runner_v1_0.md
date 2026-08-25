# Phase 6 M2 算法性能正式执行器与授权交接

## 范围

本 PR 从 PR #83 合并后的 `main` 建立，只实现并授权冻结的 M2 算法性能正式批次，不运行科学实验。

- 基线提交：`1449fd0e37d0994e20176f31630f62f00a81105f`
- 初始 Runner 实现提交：`794856b7b50e1c118b6ec8b56b34c4c30f752225`
- 最终复审修复后的 Runner 执行基线：`df24c953880f40873adb9b23f64d39fcd9bffbb9`
- 最终复审修复后的 Runner tree：`952307a5eb66d5eecf11a05d4bc9495a449c87d8`
- 命名空间：`phase6_m2_algorithm_performance_formal_v1_0`
- 输出根：`outputs/phase6_m2_algorithm_performance_formal_v1_0`

## 冻结矩阵

- 10 个全新正式种子；
- C0、T03 两个 profile；
- 每条 sequence 依次使用 $\beta=1.1,1.3$；
- 每个预算分别执行 cold、warm，各 3 次技术重复；
- 共 20 条 primary、40 组预算比较、240 次算法执行；
- 每个技术重复维持独立的跨预算 warm 状态链；
- 严格串行，禁止部分 primary、自动重试和选择性跳过。

正式 projection 在查看结果前已固定实现：逐 seed/profile/budget 先对三次技术重复取中位数，再计算 $S_{T03,1.3}$、配对确认量 $D$ 与两预算时间求和之比；使用 `numpy.Generator(PCG64DXSM)`、种子 `2026091299`、10,000 次配对 seed-cluster percentile bootstrap。加速方向只作为结果字段，不控制20/40/240执行完整性门槛。

## 门槛和授权

正式运行必须同时满足：同步的 `main/origin/main`、干净执行源、批准的五类指纹与编排器指纹、Gurobi 13.0.2、`gurobi_direct`、`Threads=1`、空输出根和显式 CLI 参数。

本 PR 合并后只授权完整 240 次 M2 算法性能批次。M0 E3 追加运行、M2 机制/OOS追加运行及 M2.1 追加运行均保持关闭。任一非最优、超时、目标不一致、制品无效或重复 primary 会形成不可变终态并停止整个批次。

最终停止语义在写入 `optimal` 制品前验证每次 worker 的性能指标、第二预算 warm 迁移链及完整 primary；证据无效时写入不可变 `evidence_invalid` 并立即停止，后续求解和下一条 primary 均不会启动。projection 若发现任何无效、失败、重复、诊断或 CRN 异常，也会立即阻断批次。

## 非执行声明

- `scenario_generation_count=0`
- `gurobi_call_count=0`
- `algorithm_performance_runs=0`
- 未修改 M2 数学模型、场景生成规则、C&CG 或 SPW-C&CG 科学实现。

Runner 提交和审批提交分离：审批文件逐字节绑定 Runner 提交中的执行制品，避免依赖未知的最终合并提交。

## 本地验证

- 正式 runner/授权专项测试：`15 passed`；
- 普通回归：`715 passed`；另有 9 项旧版本“输出目录必须不存在”断言因本机依法保留的历史正式结果目录而失败，不是代码失败；干净 CI checkout 不存在这些 D 盘制品；
- Phase 5：`6 passed`；
- Windows 可复现性专项：`16 passed`；
- `git diff --check`：通过。
