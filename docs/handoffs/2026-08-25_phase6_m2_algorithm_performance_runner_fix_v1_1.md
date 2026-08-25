# Phase 6 M2 算法性能 runner v1.1 修复说明

## 修复范围

本修复针对 PR #81 锁定的首次 pilot 失败，只修改结果封装接口：将不存在的 `DisruptedProcurementData.total_budget` 改为冻结数据类实际提供的 `DisruptedProcurementData.budget`。数学模型、场景生成、三种算法、预算、种子、容差、求解器设置和 6/12/36 pilot 矩阵均未改变。

## 隔离与测试

- 新 runner namespace：`phase6_m2_algorithm_performance_v1_1`；
- 新空输出根：`outputs/phase6_m2_algorithm_performance_v1_1`；
- 旧 v1.0 失败输出永久保留且不作为新门槛输入；
- 新增真实 `GeneratedM2Data` / `DisruptedProcurementData` 包装对象测试，在 mock 求解器返回后走完整 worker 结果封装路径，验证 `budget` 字段能够写出且不存在 `total_budget`；
- 测试不生成正式场景、不调用 Gurobi。

本文件属于两提交方案的第一提交。第二提交将审批文件精确绑定本修复提交及全部执行制品哈希，并只开放完整 6 条 primary / 36 次 pilot 求解；正式 240 次及所有其他实验继续关闭。
