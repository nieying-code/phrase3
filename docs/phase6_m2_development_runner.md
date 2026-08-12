# Phase 6 M2 Development Runner

本执行器只服务于已冻结的 M2 供应中断开发矩阵。矩阵固定为 V1、三个新开发种子、三个预算系数和 C0/C1/C2 三种履约档位，共27组，顺序为种子→预算→中断档位。

每组依次生成不可拆分的需求—履约联合场景，求解完整扩展式及其容差最优储备区间，对区间端点做逐场景精确补救重评，并对总储备比例 `0/0.1/0.3/0.5` 分别重新优化常规合同采购。完整扩展式、补救和固定策略均采用 Gurobi 13.0.2、`gurobi_direct`、`Threads=1`，V1单次调用时限为120秒。

门槛按相同 `beta-profile` 的三个种子聚合：必须3/3最优且至少2/3满足容差最优面最小储备比例不低于1%。成本、服务水平、P95、CVaR及人工趋势不参与选择。即使门槛通过，`formal_extension_authorized`仍固定为`false`；若没有组合通过，则以`no_preregistered_combination_passed`停止，不追逐参数。

执行必须同时满足配置状态`frozen_for_development_execution`和显式参数`--authorize-development-execution`。运行前验证Python/Gurobi锁、五类M2指纹、Git tree和执行输入清洁性。M0/M1授权、registry和projection不能授权M2。

每个run ID为不可变终态，失败、超时或中断后不得覆盖；诊断重试必须使用新run ID和`parent_run_id`。状态监控只读取不超过16 KiB的`status_summary.json`或projection，不解析大型result/checkpoint。全局registry与projection使用跨进程锁，整个矩阵另有串行执行锁。

本PR只冻结并实现执行器，不使用授权参数，不生成开发场景，不调用27组矩阵，也不运行pilot、正式种子或M0 E3。
