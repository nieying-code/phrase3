# Phase 6 M1 Procurement Cap Handoff

## 任务目标

在不覆盖 M0 模型和正式结果的前提下，实现独立的 M1 常规采购能力扩展。M1 只增加可选约束 `x[i,t] <= kappa*E[D[i,t]]`，并区分采购上限与预算等式产生的机械储备和所有容差最优方案都需要的稳健自主储备。

## 分支和提交

- Branch：`agent/phase6-m1-procurement-cap`
- Base branch：`main`
- Base/PR #38 merge：`0c7c6cffe82a858b534e8bf812a23291ef40b709`
- Implementation/validation commit SHA：`19936c3bf26b2eca10603f60b32da0bc689b4c31`
- Draft PR：https://github.com/nieying-code/phrase3/pull/39
- Validated PR head：`abcc6c7d8c0f855b561db40c0bc171b7cd2451e9`
- CI：[run 31459808225](https://github.com/nieying-code/phrase3/actions/runs/31459808225)，Linux `186 passed`、Phase 5 `6 passed`、Windows复现检查成功

## 修改内容

### 模型

- 新增 M1 专用数据类型和约束包装器；M0 公共模型文件保持未修改。
- 关闭容量时直接复用原始 M0 数据对象且不生成新增约束。
- 开启容量时按冻结理论期望生成逐物资、逐时期采购上限。
- 保留 `regular_cost + R = B`，不增加闲置资金或强制正储备。
- 新增最低可行储备 LP及闭式核验。
- 在完整扩展式的容差最优面上分别最小化和最大化储备，并对两个端点逐场景精确补救重评。

### 算法和策略

- 新增 M1 专用完整扩展式、标准 C&CG 和 SPW-C&CG 入口。
- M1 复用现有库存和补救约束，但不修改 M0 的受保护组件或指纹。
- 新增 `rho={0,0.1,0.3,0.5}` 固定自主储备策略，每个比例均建立新模型并重新优化灾前采购。

### 复现与执行边界

- M1 使用独立科学配置、runner配置、组件指纹、环境指纹、命名空间和输出根目录。
- 机器审计锁定本地受控 Gurobi 主机的环境指纹；跨平台 CI 只重算并验证环境记录有效，不要求 Linux 硬件环境与本地执行主机哈希相同。未来 M1 实验仍必须匹配已批准的本地环境指纹。
- 当前配置为 `candidate_design_pending_review`，入口只允许 `--validate-only`。
- M1 不接受 M0 authorization、registry 或 projection。
- 本次没有运行63组开发矩阵、pilot、正式种子或 M0 E3正式实验。

## 关键数学与实现决策

1. 正式机械储备下界由第一阶段 LP 给出；闭式值只做一致性核验。
2. 自主储备不使用求解器任意返回的单个 `R`，而使用完整扩展式上的 `R_min_opt`。
3. `R_disc_robust=max(0,R_min_opt-R_min_feas)`；激活阈值分别为严格大于 `1e-4` 和大于等于 `1%`。
4. 最优面目标容差沿用冻结的绝对/相对一致性公式。
5. 固定策略以机械下界之外的可配置预算为基数，避免把机械剩余误称为自主储备。
6. 应急价格和缺货惩罚保持基准值，本轨道不做联动敏感性。

## 修改文件

- `src/phase6_m1.py`：M1数据、模型、求解器接口、储备区间和指纹。
- `src/run_phase6_m1.py`：设计阶段只读验证入口。
- `configs/phase6_m1_procurement_cap.yaml`：科学协议和63配置预注册。
- `configs/phase6_m1_runner.yaml`：独立runner命名空间与Gurobi约束。
- `tests/test_phase6_m1_procurement_cap.py`：模型和小规模算法测试。
- `tests/test_phase6_m1_procurement_cap_audit.py`：机器审计与指纹闭合。
- `docs/phase6_m1_procurement_cap_model.md`：数学模型说明。
- `docs/phase6_m1_development_preregistration.md`：开发矩阵预注册。
- `docs/handoffs/2026-08-11_phase6_m1_procurement_cap_audit.json`：紧凑机器审计。

## 验证结果

- `python -m py_compile src/phase6_m1.py src/run_phase6_m1.py`：通过。
- `python -m pytest tests/test_phase6_m1_procurement_cap.py -q`：`17 passed`。
- `python -m pytest -q`：`192 passed in 38.55s`。
- Gurobi Optimizer/gurobipy：13.0.2。
- Pyomo接口：`gurobi_direct`。
- Threads：1。

## 预注册但未执行

- 开发种子：`2026081101/02/03`。
- `beta={0.9,1.1,1.3}`。
- `kappa={无上限,1.5,1.3,1.2,1.1,1.0,0.8}`。
- 共63个科学配置。
- 进入后续正式设计需3/3成功且至少2/3达到实质自主激活；禁止按成本、服务水平或人工趋势选择。

## 已知限制

- 本PR只实现和验证设计接口，没有提供M1完整实验runner、registry聚合或投影授权。
- 未运行开发矩阵，因此没有关于自主储备是否激活的经验结论。
- 未引入采购提前期、供应中断、到货率或新的风险参数。

## 风险点与审查重点

1. M1约束包装器是否在完整扩展式和每个受限主问题中一致生效。
2. M0关闭对照是否完全不生成容量约束，且M0指纹保持不变。
3. 最优储备区间是否来自完整扩展式而非受限主问题。
4. 最优面两端是否均使用独立补救模型重评。
5. 固定策略是否重新优化采购且保持预算等式。
6. 63配置和激活门槛是否已预注册但未被执行。

## 下一步建议

本Draft PR通过复审并由用户手动合并后，应另建冻结设计PR。只有再次明确授权，才可在独立M1输出根目录运行预注册开发矩阵；不得继承M0正式授权。
