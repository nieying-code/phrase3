# 阶段3扩展式与阶段4标准 C&CG

## 1. 范围

PR #1 的实现标签曾统一写作“阶段3”，但按 `docs/project_plan.md` 和原始项目说明，内生储备扩展式属于阶段3，标准有限场景 C&CG 属于阶段4。本文件覆盖这两个阶段。SPW-C&CG 与跨预算场景池热启动属于阶段5；并行 oracle、机器学习、配送路径和严格二进制 FIFO 不属于阶段3/4。

## 2. 第一阶段

第一阶段变量为常规采购量 \(y_{kt}\ge 0\)、应急储备金 \(R\ge 0\) 和最坏补救成本上界 \(\theta\ge 0\)。内生储备模型采用预算等式

\[
\sum_{k,t}c^0_{kt}y_{kt}+R=B.
\]

该等式把未承诺给常规采购的预算全部定义为可用应急额度，使 \(R/B\) 可识别。\(R\) 是可用上限而非已经发生的成本，因此不直接进入目标；真实应急支出由 \(p_{\omega kt}q_{\omega kt}\) 计入补救成本。

## 3. 第二阶段和库存时点

每个场景 \(\omega\) 具有应急采购 \(q\)、消费 `consume`、消费前分库龄可用量 `available`、过期处置后的期末库存 `inventory`、缺货 `shortage` 和到期浪费 `waste`。

最新库龄流入为

\[
available_{\omega kt0}
=y_{kt}+q_{\omega kt}+\mathbf 1_{\{t=1\}}I^0_{k0}.
\]

较旧库龄在第一期来自对应初始库存，以后来自上一期期末较新一档库存。非最后库龄满足

\[
available=consume+inventory,
\]

最后库龄满足

\[
available=consume+waste,\qquad inventory=0.
\]

消费加缺货等于需求。仓储容量在消费和过期处置后计量，只包括仍能结转的期末库存。应急采购受场景供应上限和

\[
\sum_{k,t}p_{\omega kt}q_{\omega kt}\le R
\]

约束。

## 4. 精确补救模型

给定 \(y,R,\omega\)，独立补救模型固定全部第一阶段变量，只最小化

\[
Q(y,R,\omega)=
\sum_{k,t}p_{\omega kt}q_{\omega kt}
+\sum_{k,t}\pi^s_k shortage_{\omega kt}
+\sum_{k,t}\pi^w_k waste_{\omega kt}.
\]

求解状态严格区分 `optimal`、`infeasible`、`time_limit`、`solver_error` 和 `unknown`。求解失败或超时不能解释为不可行。

## 5. 全场景扩展模型

受限主问题构造器 `build_restricted_master(data, scenario_names)` 为指定场景创建完整补救变量和约束，并求解

\[
\min\ \sum_{k,t}c^0_{kt}y_{kt}+\theta
\]

满足预算等式及

\[
\theta\ge Q(y,R,\omega),\quad \omega\in\Omega_k.
\]

全部场景扩展模型等价于把完整训练场景集合传入同一构造器。

扩展模型内部只有决定 \(\theta\) 的最坏场景必须达到其最小补救成本；其他场景变量只需保持成本不超过 \(\theta\)，因此不能用于逐场景报告。求出 \(y,R\) 后，代码用独立补救模型重新求解全部场景，并检查

\[
z_{\mathrm{extensive}}
\approx
C^0(y)+\max_{\omega\in\Omega}Q_{\mathrm{exact}}(y,R,\omega).
\]

所有逐场景应急采购、缺货、浪费、库存和成本输出均来自该独立评价。

## 6. 标准有限场景 C&CG

初始集合去重合并：

1. 按需求、应急价格和应急供应的标准化分量距离最接近均值的场景；
2. 总需求最高场景；
3. 平均应急价格最高场景；
4. 总应急供应最低场景。

第 \(k\) 次迭代：

1. 求解 \(\Omega_k\) 上的受限主问题，得到 \(y_k,R_k\) 和 `LB`；
2. 固定 \(y_k,R_k\)，用独立补救模型枚举完整候选集合；
3. 若存在补救不可行场景，优先添加一个尚未加入的不可行场景，且本轮不检查收敛；
4. 若全部场景补救最优可行，计算最坏精确补救成本及
   \[
   candidate\_UB=C^0(y_k)+\max_\omega Q(y_k,R_k,\omega);
   \]
5. 用历史最小 `candidate_UB` 更新全局 `UB` 和 incumbent；
6. 当
   \[
   UB-LB\le abs\_tol+rel\_tol\max(1,|UB|)
   \]
   时停止，否则只加入一个未出现过的最坏场景。

若最坏场景已经在主问题中但 gap 仍超差，算法返回 `inconsistent_repeated_worst_scenario`，不以“场景重复”为理由强行宣告收敛。迭代次数同时受配置上限和有限场景数约束。

## 7. 上下界

受限主问题只考虑场景子集，因此其最优值是完整问题的下界。完整 oracle 对当前第一阶段解计算的真实鲁棒目标是可行上界。只有所有场景补救均达到 `optimal` 时，该上界才有效。

## 8. FIFO、容量与已知限制

当前连续 LP 不用 Big-M 或二进制变量强制严格 FIFO。在非负浪费成本下至少存在 FIFO 最优解，但退化时求解器可能返回等价的非严格 FIFO 解；因此不把具体库龄消费顺序解释为唯一政策。阶段3仍采用消费和到期处置后的期末仓储容量口径，不限制到货瞬间的临时占用。

阶段4应在本阶段一致性验证基础上实现跨预算场景池热启动，并分别统计冷启动和热启动的迭代次数、主问题时间和 oracle 时间。
