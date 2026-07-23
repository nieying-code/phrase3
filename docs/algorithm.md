# 标准 C&CG 与 SPW-C&CG（阶段 1 初稿）

## 1. 标准有限场景 C&CG

输入完整候选场景集 `Omega`、预算 `B`、绝对容差、相对容差和最大迭代数。受限主问题包含场景子集 `S` 的完整补救变量与约束。

### 1.1 基础初始化场景

去重合并以下场景：

1. 与逐期均值向量最接近的场景；距离在标准化后的需求、价格、供应向量上计算。
2. 总需求最大的场景。
3. 风险指数最大的场景；风险指数定义为“平均应急价格标准分数减平均供应标准分数”。

### 1.2 伪代码

```text
S <- base_scenarios(Omega)
best_ub <- +infinity
best_solution <- None

for iteration = 1,...,max_iterations:
    solve restricted master over S
    (y, R, theta) <- master solution
    lb <- C0(y) + theta

    solve recourse LP for every omega in Omega at fixed (y,R)
    if any recourse solve failed or timed out:
        stop with solver failure
    if any recourse is infeasible:
        omega_star <- one infeasible scenario
        ub_candidate <- +infinity
    else:
        omega_star <- argmax Q(y,R,omega)
        ub_candidate <- C0(y) + Q(y,R,omega_star)
        if ub_candidate < best_ub:
            best_ub <- ub_candidate
            best_solution <- (y,R)

    gap <- best_ub - lb
    if all recourse feasible and
       gap <= abs_tol + rel_tol * max(1, abs(best_ub)):
        return best_solution and iteration log

    if omega_star in S:
        stop with numerical-stagnation diagnostic
    S <- S union {omega_star}
```

主问题目标是全场景扩展式的松弛，因此给出下界。固定第一阶段解后对完整场景集求得的最大补救成本给出该解的真实鲁棒目标，从而形成可行上界。日志至少记录：迭代、LB、当前/历史最好 UB、gap、`R`、`R/B`、主问题场景数、最坏场景、主问题时间、补救总时间、各状态数量。

## 2. SPW-C&CG

预算按升序 `B1 < ... < Bm` 求解。第一个预算使用基础场景。预算 `Bj` 的初始池定义为

```text
S0(Bj) = base_scenarios
         union active_scenarios(Bj-1)
         union worst_scenarios_ever(Bj-1).
```

活跃场景采用求解器无关定义：在上一预算最终主问题中满足

```math
\theta-Q(y,R,\omega)\le \epsilon_{active}
```

的场景。若求解器提供可靠对偶信息，可额外记录非零对偶场景，但不把它作为唯一标准。

`worst_scenarios_ever` 是上一预算每次迭代产生过的最坏或不可行场景集合。第一版不裁剪历史池；后续若池过大，可按出现次数、最后出现预算和活跃性排序保留前 `M` 个，但无论如何完整场景 oracle 不得裁剪。

## 3. 最优性保持理由

对任一预算，SPW-C&CG 的初始池只是完整集合 `Omega` 的一个子集。池中的每个场景都是原问题的有效场景，因此加入它们只会使初始受限主问题更紧，不会删除任何原问题约束。此后最坏场景步骤仍精确扫描全部 `Omega`，并在违反时加入场景。由于 `Omega` 有限且重复场景不会再次加入，算法在有限次场景加入后达到与完整扩展式相同的最优值。

必须通过实验同时验证：

- 冷启动和热启动最终目标在容差内一致；
- 两者第一阶段解的完整场景可行性一致；
- 小规模下两者均与全场景扩展式一致。

## 4. 与变量 warm start 的区分

场景池热启动改变初始主问题的约束/变量块，是 SPW-C&CG 的核心。把上一预算的 `y`、`R` 或补救变量作为求解器初值是独立技术，可能受求解器接口支持程度影响。实验报告分四种设置时应明确标注：冷场景/冷变量、热场景/冷变量、冷场景/热变量、热场景/热变量。第一版至少实现前两种。

## 5. 公平计时

- 冷启动与热启动使用同一求解器、线程数、容差和场景顺序。
- 热启动总时间包括初始池构造和主问题建模时间。
- 同时报告 wall-clock、主问题累计时间、补救累计时间、迭代数和最终场景数。
- 每组预算和随机种子交替运行冷/热顺序，降低缓存和系统负载偏差。
- 报告中位数与四分位区间，不只报告单次最好结果。
