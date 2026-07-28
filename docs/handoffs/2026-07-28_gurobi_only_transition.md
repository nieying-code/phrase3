# Gurobi-only Transition Handoff

## 任务目标

将项目从可回退的多求解器配置切换为 Gurobi 13.0.2 单一求解器策略，
防止后续试运行和正式实验混入 HiGHS 结果，并明确既有结果的保留边界
与 Phase 6 重跑范围。

## 分支和提交

- Branch：`agent/gurobi-only`
- Base branch：`main`
- Base commit：`11ad04d6d1cb5f95239b83e7a9b31eea7885bc92`
- Implementation commit：`c3f62f224add53963b4438fc6d16768ec2fb151c`
- PR：[https://github.com/nieying-code/phrase3/pull/6](https://github.com/nieying-code/phrase3/pull/6)

## 修改内容

### 求解器与依赖

- `requirements.txt` 删除 `highspy`，固定 `gurobipy==13.0.2`。
- 所有正式配置的求解器列表固定为 `[gurobi]`。
- 公共求解入口只接受严格的 `("gurobi",)`，通过 Pyomo
  `gurobi_direct` 使用 Python 接口；其他求解器或回退列表在求解前
  返回明确错误。
- 运行时同时强制 `gurobipy` 发行版和实际加载的 Gurobi Optimizer
  等于 13.0.2；版本不匹配时拒绝创建求解器。
- Gurobi 的单次时限、线程数、可行性容差和最优性容差分别映射到
  `TimeLimit`、`Threads`、`FeasibilityTol` 和 `OptimalityTol`。
- 环境检查和可复现 manifest 只记录 Gurobi，不再探测或运行 HiGHS。
- Phase 6 E3 组件依赖指纹由 `highspy` 改为 `gurobipy`。

### Phase 6

- runner 在加载配置时强制 `preference == [gurobi]`，早于场景生成。
- runner 在场景生成前执行 Gurobi 发行版与 Optimizer 双重版本预检。
- 更新遗留 D0 配置的规范化文件哈希，使冻结协议能够检测本次正式
  求解环境变更。
- 旧 HiGHS pilot 的科学/runner/组件指纹不再满足新的正式推进门槛。

### 测试与文档

- 所有活跃求解测试改为 Gurobi。
- 新增非 Gurobi 求解器拒绝测试及 Phase 6 非 Gurobi 配置拒绝测试。
- 新增 Python 包版本、Optimizer 版本以及 Phase 6 预检顺序测试。
- 新增 `docs/gurobi_only_policy.md`，记录历史结果边界和重跑规则。
- 历史 handoff 不改写，继续如实保留当时使用 HiGHS 的事实。

## 验证结果

运行环境：

- Python：Codex Python 3.12
- Pyomo：6.10.1
- Gurobi Optimizer / `gurobipy`：13.0.2
- 接口：`gurobi_direct`
- 许可证：学术非商业许可证，本地验证有效至 2027-07-28
- 线程数：1

实际命令与结果：

```text
python -m compileall -q src tests
结果：通过

python -m pytest -q
结果：73 passed in 31.70s

python -m src.run_phase3 --config configs/phase3.yaml \
  --output outputs/gurobi_validation/phase3
结果：
  extensive_status = optimal
  extensive_objective = 3269.9644075814276
  ccg_status = optimal
  ccg_objective = 3269.9644075814276
  objective_difference = 0
  ccg_iterations = 5
  acceptance_status = passed

python -m src.run_phase5 --config configs/phase5.yaml \
  --output outputs/gurobi_validation/phase5
结果：
  status = optimal
  budgets = 700, 800, 900, 1000, 1100, 1200
  max_objective_difference = 0
  total_iteration_reduction = 13
```

基线最终 CI：GitHub Actions
[run #30375599593](https://github.com/nieying-code/phrase3/actions/runs/30375599593)
成功；普通回归和 Phase 5 端到端验证均使用 Gurobi-only 依赖完成。
版本强制复审修复的提交与 CI 将在本节下方追加。

## 既有结果处置

- 阶段 1–5 的模型、算法和 HiGHS 数值验证保留，无需回滚或完整重跑。
- 阶段 3/4 和阶段 5 已通过本次 Gurobi 代表性交叉验证。
- 旧 HiGHS 运行时间、迭代统计、吞吐率和加速比不得进入 Gurobi 正式
  性能结论。
- Phase 6 已完成的 V1/V2 HiGHS pilot 只作历史跨求解器证据。
- 已中断的 P1 HiGHS 运行继续保留为诊断记录，不得恢复或计为完成。
- Phase 6 正式实验尚未开始，没有正式结果需要废弃。

## 下一步

1. 合并本 PR 后，在固定提交和 Gurobi-only 环境上生成新的 run ID。
2. 重跑 V1、V2、P1、P2 各三个 pilot seed，共 12 条预算序列。
3. 只用新的 Gurobi pilot 重新计算吞吐率和计算量推进门槛。
4. 门槛通过、执行器完整并完成审查后，再启动正式种子。

## 已知限制与风险

- GitHub Actions 不得使用或存储本地学术许可证；CI 只运行适合
  Gurobi 默认受限环境的小规模测试，正式规模验证必须在本地许可环境。
- 线性规划存在多重最优解时，Gurobi 与历史 HiGHS 第一阶段变量、
  场景加入顺序或迭代次数可能不同；正式结论按冻结容差比较目标与指标。
- 本次不运行任何 Phase 6 formal seed，也不运行 P3/P4。

## ChatGPT 审查清单

1. 是否存在任何活跃 HiGHS 首选、回退或执行路径；
2. `select_solver()` 是否只能返回 `gurobi_direct`；
3. `gurobipy` 和实际 Optimizer 是否都严格锁定到 13.0.2；
4. 非 Gurobi 配置或错误版本是否在场景生成与求解前失败；
5. Gurobi 时限、线程和容差参数映射是否正确；
6. Phase 6 指纹是否包含 `gurobipy` 和本次组件变更；
7. 旧 HiGHS pilot 是否被排除在新推进门槛之外；
8. 历史结果保留与正式性能统计边界是否清楚；
9. CI 是否没有提交、打印或依赖私人许可证。
