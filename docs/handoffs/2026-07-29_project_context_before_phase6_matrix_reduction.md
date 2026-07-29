# Project Context Before Phase 6 Matrix Reduction

## 1. 文档用途

本文档用于把当前项目完整移交给一个没有读过历史聊天的新 Codex/ChatGPT
会话。接手者不得假设了解此前讨论，必须先阅读本文档和仓库根目录
`AGENTS.md`。

本文档记录的是 **2026-07-29 的暂停点**：

- 阶段1–5的模型、算法和工程修复已经完成并合并；
- 阶段6正式实验尚未开始；
- 旧版阶段6矩阵计算规模过大，正在讨论精简；
- 在精简方案受审并重新冻结前，不得继续旧矩阵 pilot 或启动正式种子；
- 本文档本身不修改实验矩阵。

## 2. 正式位置与Git状态

- 原始项目说明：
  `D:\新建文件夹\项目.docx`
- 正式仓库：
  `D:\新建文件夹\项目交付\阶段3-4修复同步\phrase3`
- GitHub：
  `https://github.com/nieying-code/phrase3`
- 默认分支：
  `main`
- 当前已合并主线提交：
  `948219b64e68e21ef8e115de62ca374dd1fc8772`
- 当前本地功能分支：
  `agent/phase6-gurobi-pilots`

当前分支基于已合并的PR #6主线。阶段6实验暂停期间，不得直接向
`main`提交，不得自动合并PR。

## 3. 研究问题与模型主线

项目研究固定总预算下、多期易腐救灾物资采购问题。灾害发生前决定常规
采购和应急储备；需求、应急价格与应急供应揭示后，再决定应急采购、
库存使用、缺货和过期处置。

第一阶段变量：

- `y[k,t]`：灾前常规采购；
- `R`：应急储备金；
- `theta`：训练场景中的最坏补救成本上界。

内生预算规则：

```text
sum(c0[k,t] * y[k,t]) + R = B
```

`R`是灾后可用预算上限，不是已经发生的成本，因此不重复加入目标。
真实应急支出只通过场景补救变量计入补救成本。

场景补救成本包括：

- 应急采购成本；
- 缺货惩罚；
- 到期浪费惩罚。

鲁棒目标：

```text
min regular_cost(y) + theta
theta >= Q(y, R, omega)  for every training scenario omega
```

库存采用分库龄流转：

- 最新库龄接收常规采购、应急采购和第一期初始最新库存；
- 其他库龄来自上一期期末较新一档库存；
- 最老库存当期消费或浪费，不能继续结转；
- 仓储容量只计算仍可结转的期末库存；
- 消费与缺货共同满足需求。

关键正确性规则：

> 扩展式模型内部非最坏场景的补救变量不能直接用于逐场景报告。
> 得到第一阶段 `y,R` 后，必须对每个场景重新求解独立补救模型。

因此正式验收检查：

```text
extensive objective
≈ regular cost + max(exact independent recourse cost)
```

## 4. 算法主线

项目已经实现：

1. 全训练场景内生储备扩展式；
2. 固定第一阶段决策的独立单场景补救模型；
3. 完整有限场景最坏情形oracle；
4. 标准有限场景C&CG；
5. 跨预算场景池热启动SPW-C&CG；
6. 冷启动与热启动的精确目标一致性检查；
7. 失败、超时、不可行、部分结果、断点和并发写入保护。

标准C&CG中：

- 受限主问题目标提供LB；
- 固定第一阶段方案后，完整场景oracle给出候选UB；
- 只有所有补救模型均最优时才能检查收敛；
- 每次加入一个未重复场景；
- 不可行场景优先加入；
- 最坏场景已在主问题但gap未闭合时不能强行终止。

SPW-C&CG中：

- 热池由基础场景、上一预算活跃场景和累计历史对抗场景去重组成；
- 完整场景oracle始终保留，因此热启动不改变精确最优解；
- 只有完整、最优且冷/热目标一致的预算状态才能向后传递。

## 5. 阶段编号与完成状态

原始项目计划的正式编号为：

- 阶段1：文献、研究问题、假设、数学框架；
- 阶段2：数据结构、场景生成、确定性与固定比例基线；
- 阶段3：全场景内生储备扩展式；
- 阶段4：标准有限场景C&CG；
- 阶段5：SPW-C&CG跨预算场景池热启动；
- 阶段6：正式数值实验、性能、机制、敏感性和样本外评价。

早期PR曾把阶段3和阶段4统一称为“Phase 3”，后来已在文档中澄清；
SPW-C&CG按原始计划统一为阶段5。

当前结论：

- 阶段1–5：核心模型、算法、测试和工程验收已基本完成；
- 阶段6：runner和实验协议已实现，但正式实验尚未启动；
- 不得把已有小规模验证描述为正式大规模统计结论。

## 6. 已合并的GitHub协作历史

- PR #1：内生储备扩展式与标准C&CG；
- PR #2：SPW-C&CG及失败诊断；
- PR #3：阶段3/4验收、可复现性与运行门槛修复；
- PR #4：阶段6实验矩阵设计；
- PR #5：阶段6生成器、runner、heartbeat、断点、注册表和并发锁；
- PR #6：全项目切换为Gurobi-only并强制版本。

所有PR均由Codex创建、用户交给ChatGPT复审、Codex在同一PR修复、
用户最终手动合并。后续继续采用这一流程，Codex不得自动合并。

## 7. 当前唯一允许的运行环境

仓库专用解释器：

```text
D:\新建文件夹\项目交付\阶段3-4修复同步\phrase3\.venv-gurobi\Scripts\python.exe
```

该解释器同时供PyCharm和Codex使用。Codex不需要控制PyCharm界面，
而是直接调用同一个`python.exe`。

冻结版本：

- Python `3.12.10`
- Pyomo `6.10.1`
- NumPy `2.5.1`
- pandas `3.0.5`
- PyYAML `6.0.3`
- matplotlib `3.11.1`
- pytest `9.1.1`
- psutil `7.2.2`
- filelock `3.32.0`
- gurobipy `13.0.2`
- Gurobi Optimizer `13.0.2`

依赖锁文件：

```text
requirements-gurobi-lock.txt
```

基础Python安装在：

```text
D:\Tools\Python312\python.exe
```

基础解释器不能直接用于项目运行，因为项目依赖安装在`.venv-gurobi`。

禁止使用：

- Codex自带Python；
- `D:\pycharm.projects\.venv`；
- 系统Python 3.11；
- `D:\Tools\Python312\python.exe`直接跑项目；
- 任意未锁定的临时Python环境。

最新环境验证：

```text
Gurobi runtime preflight: passed
Academic license: valid
Threads: 1
Full regression: 75 passed in 38.20s
```

## 8. 求解器永久政策

从PR #6开始，全项目只能使用：

```text
gurobipy 13.0.2
Gurobi Optimizer 13.0.2
Pyomo interface: gurobi_direct
Threads: 1
```

代码会同时核验`gurobipy`发行版与实际Optimizer版本。版本不符时，
阶段6必须在场景生成前停止。

永久禁止：

- HiGHS；
- `highspy`；
- 自动求解器回退；
- 在不同求解器结果之间混合正式计时；
- 把旧HiGHS pilot计入Gurobi正式门槛。

旧HiGHS结果只可作为历史调试证据，不进入后续正式论文统计。

## 9. Git环境

PyCharm长期使用的Git：

```text
C:\Program Files\Git\cmd\git.exe
git version 2.45.1.windows.1
```

已验证：

- 正式目录是Git仓库；
- 当前分支可识别；
- `origin`指向正确GitHub仓库；
- `git ls-remote`能够读取GitHub主线。

`.idea/`已加入`.gitignore`，不得提交PyCharm个人配置。

## 10. 2026-07-29卡顿事件

当天“运行卡住”不是Gurobi求解器卡死，也不是Python版本问题。

真实原因：

1. Gurobi pilot已经正常完成；
2. 后续状态检查使用PowerShell `ConvertFrom-Json`读取约7–15 MB、
   且高度嵌套的`result.json`/`checkpoint.json`；
3. PowerShell解析失败并向终端倾倒超过25万token的内容；
4. Codex界面被巨大输出拖住，看起来像实验一天没有进展。

已采取修复：

- 新增`src/phase6_status.py`；
- 新增`tests/test_phase6_status.py`；
- 状态工具只输出运行状态、预算完成数、冷/热状态计数、最大目标差、
  求解器、运行环境、进程和文件大小；
- 输出有16 KiB硬上限；
- 约7.9 MB结果只生成约1.6 KiB摘要；
- 进程扫描已避免把状态查询命令自身误判为实验。

以后查询命令：

```powershell
.\.venv-gurobi\Scripts\python.exe -m src.phase6_status `
  --output outputs `
  --run-id <RUN_ID>
```

永久禁止：

- PowerShell `ConvertFrom-Json`读取Phase 6大型JSON；
- 向终端打印完整结果、checkpoint、逐场景成本或完整迭代日志；
- 用shell直接展开大型嵌套JSON。

## 11. 当前Phase 6运行状态

Phase 6已暂停，不能自动恢复。

现有新Gurobi pilot：

### `pilot_gurobi_v1_2026072001`

- 状态：`optimal`
- 预算：`6/6`
- 冷/热算法行：完整
- 最大目标差：约`3.638e-12`
- 求解器：`gurobi_direct`
- Gurobi：`13.0.2`
- 线程：`1`

### `pilot_gurobi_v1_2026072002`

- 状态：`optimal`
- 预算：`6/6`
- 冷/热算法行：完整
- 最大目标差：`0.0`
- 求解器：`gurobi_direct`
- Gurobi：`13.0.2`
- 线程：`1`

这两条使用的是旧的Codex Python 3.12.13加相同Gurobi版本。其数学正确性
证据可以保留，但如果后续论文要求所有计时来自统一`.venv-gurobi`
环境，则必须使用新run ID重新运行，不能覆盖旧run。

未启动：

```text
pilot_gurobi_v1_2026072003
V2 Gurobi pilots
P1 Gurobi pilots
P2 Gurobi pilots
全部formal seeds
P3
P4
```

旧矩阵当前投影：

```text
status = insufficient_pilot_coverage
completed = 2/12
compute_gate_passed = false
formal_execution_authorized = false
```

上述`2/12`只描述旧矩阵。因为正在讨论精简矩阵，不得为追求`12/12`
而继续运行。

当前看到的两个Python进程是PyCharm控制台的虚拟环境入口和基础解释器
子进程，不是Phase 6实验。

## 12. 当前未提交的本地修改

当前分支上存在以下与环境和卡顿修复相关的未提交修改：

- `.gitignore`
  - 忽略`.venv-gurobi/`和`.idea/`；
- `AGENTS.md`
  - 永久记录Python、Gurobi和大文件监控规则；
- `requirements-gurobi-lock.txt`
  - 固定项目实际依赖版本；
- `src/phase6_status.py`
  - 安全紧凑状态工具；
- `tests/test_phase6_status.py`
  - 大结果输出上限与checkpoint测试；
- 本handoff文档。

未跟踪输出：

- `outputs/gurobi_validation/`
- `outputs/tmp/`

这些输出不得在未检查内容、大小和用途前提交。原始Phase 6大型outputs默认
不进入Git。

当前尚未为上述修改创建新PR。接手者必须先检查`git diff`和
`git status`，不得覆盖或丢弃这些修改。

## 13. 旧版Phase 6矩阵

旧矩阵文件：

```text
configs/phase6_experiment_matrix.yaml
docs/phase6_experiment_matrix.md
```

原规模档位：

| 档位 | 物资 | 时期 | 训练场景 | 原正式种子 |
|---|---:|---:|---:|---:|
| D0 | 1 | 4 | 20 | 开发种子 |
| V1 | 1 | 6 | 50 | 10 |
| V2 | 1 | 6 | 100 | 10 |
| P1 | 3 | 12 | 500 | 10 |
| P2 | 5 | 12 | 1000 | 10 |
| P3 | 5 | 24 | 2500 | 5 |
| P4 | 5 | 24 | 5000 | 3 |

旧算法比较使用：

- 六个预算；
- 冷、热两种算法；
- V1/V2/P1三次技术重复；
- P2/P3/P4一次重复；
- 合计1296次算法执行；
- 十次C&CG迭代估算约684万次补救LP；
- 200次迭代上限约1.368亿次补救LP。

旧敏感性包含11个单因素、四因素全因子筛选和库存×供应交互；
样本外评价使用5000测试场景和8种策略。

这个设计统计上很完整，但明显超过“完成一篇结构完整论文”的最低必要
计算量。

## 14. 正在讨论的精简方向

用户明确表示：

> 不希望项目过度复杂，只需要形成一篇完整论文；希望删除不必要实验，
> 合并重复档位并降低时间成本。

当前建议尚未写入矩阵、尚未重新冻结：

### 档位

- D0：只作自动回归，不进入论文主实验；
- V1：少量正确性金标准；
- V2：主模型比较、正式统计、样本外和敏感性；
- P1：保留为多物资、多时期中规模验证；
- P2：只保留少量较大规模压力测试；
- P3：删除；
- P4：删除。

### 预算

由六档缩减为三档：

```text
0.90 B_ref
1.10 B_ref
1.30 B_ref
```

三个预算代表紧张、正常/过渡、宽松，并保留两次跨预算状态传递。

### 种子与计时

建议：

- V1：3个种子，1次运行；
- V2：10个种子，3次计时重复，作为主要统计档；
- P1：5个种子，1次运行；
- P2：3个种子，1次运行；
- P3/P4：不运行。

对应算法执行约：

```text
V1 = 3 × 3 × 2 × 1 = 18
V2 = 10 × 3 × 2 × 3 = 180
P1 = 5 × 3 × 2 × 1 = 30
P2 = 3 × 3 × 2 × 1 = 18
total = 246
```

相对旧矩阵1296次，约减少81%。

### 策略

由8种缩减为6种：

- 确定性；
- 零储备；
- 固定10%；
- 固定30%；
- 固定50%；
- 内生储备。

删除固定20%和40%，保留低、中、高固定比例曲线。

### 敏感性

从11个因素和大规模全因子实验，缩减为与论文贡献直接相关的5个因素：

- 需求波动；
- 应急价格水平；
- 应急供应削减；
- 保质期；
- 仓储容量。

每个因素采用低、基准、高三水平，公共基准只运行一次：

```text
1 + 5 × 2 = 11个唯一配置
```

另外只保留：

```text
保质期 × 应急供应削减
```

的`2×2`小型交互实验。

### 样本外

- 只在V2执行；
- 5个训练种子；
- 三个预算；
- 六种策略；
- 每组测试场景由5000降至2000；
- 仍严格报告不可行、求解失败、服务水平、缺货概率、成本分位数和CVaR95；
- 不允许用Big-M伪造不可行成本。

### 精简后仍能支持的论文结论

1. 扩展式、标准C&CG和SPW-C&CG目标一致；
2. 内生储备相对零储备和固定比例的决策价值；
3. 储备金额与比例随预算和风险变化；
4. SPW-C&CG保持精确性并减少迭代或时间；
5. 模型可扩展到多物资、多时期和1000训练场景；
6. 样本外成本尾部、缺货和服务水平表现；
7. 保质期和灾后供应风险的交互作用。

P3/P4主要增加极限压力测试证据，不是论文闭环所必需。

## 15. 精简前必须决定的事项

接手后的首个实质任务不是运行实验，而是形成并审查新版矩阵。需要明确：

1. 是否正式删除P3/P4；
2. P2是否保留3个描述性种子；
3. V2是否继续使用10个正式种子和3次技术重复；
4. 三个预算是否固定为`0.90/1.10/1.30`；
5. 策略是否缩减为6种；
6. 样本外场景是否降为2000；
7. 敏感性是否缩减为5个主因素加一个`2×2`交互；
8. 论文是否只作受控合成方法论文，还是最后补一个小型真实校准案例。

真实数据不是算法正确性前提。若无法及时获得高质量可追溯数据，可以把论文
定位为受控合成数值研究，并明确外部有效性限制；若能获得可靠数据，建议只补
一个V2级案例，不再复制全套矩阵。

## 16. 下一步推荐流程

1. 保持Phase 6暂停；
2. 用户确认精简原则；
3. 修改机器可读矩阵和论文式说明，升级`schema_version/matrix_id`；
4. 同步修改runner门槛、投影、测试和所需输出；
5. 运行完整测试，不运行正式种子；
6. 创建handoff、commit、push和Draft PR；
7. 用户把PR链接交给ChatGPT审查；
8. 在同一PR闭环审查意见；
9. 用户手动合并；
10. 只按新版矩阵重新运行必要pilot；
11. 计算门槛通过后，才启动新版正式种子。

不得因为旧投影显示`2/12`就继续旧pilot。矩阵变化后，pilot清单和指纹必须
按新版重新计算。

## 17. 新会话必须遵守的边界

- 不移动或重命名正式仓库；
- 所有交付物保留在D盘；
- 不删除、覆盖、reset或stash用户修改；
- 不恢复旧HiGHS实验；
- 不使用同一run ID覆盖失败或旧环境结果；
- Phase 6必须串行运行，避免污染计时；
- 未经明确授权不得运行formal seeds、P3或P4；
- 不打印大型JSON；
- 不自动合并PR；
- 每个可提交任务都更新handoff；
- 收到ChatGPT审查意见后在同一分支、同一PR修复。

## 18. 新聊天启动指令

以下内容可直接复制到新的Codex聊天：

```text
请接手正式仓库：
D:\新建文件夹\项目交付\阶段3-4修复同步\phrase3

开始前完整阅读：
1. AGENTS.md
2. docs/handoffs/2026-07-29_project_context_before_phase6_matrix_reduction.md
3. configs/phase6_experiment_matrix.yaml
4. docs/phase6_experiment_matrix.md

当前目标不是运行实验，而是基于handoff中的精简建议重新设计并审查
Phase 6实验矩阵，使其足以支持一篇完整论文，同时显著降低计算量。

强制边界：
- 保持现有仓库路径；
- 使用且只使用
  D:\新建文件夹\项目交付\阶段3-4修复同步\phrase3\.venv-gurobi\Scripts\python.exe
- 只允许Gurobi/gurobipy 13.0.2、gurobi_direct、Threads=1；
- 禁止HiGHS及任何回退；
- 不运行任何pilot、formal seed、P3或P4，直到新版矩阵完成、测试通过、
  PR经ChatGPT审查并由用户合并；
- 禁止PowerShell ConvertFrom-Json读取Phase 6大型结果；
- 先检查git status并保留现有未提交修改；
- 不自动合并PR。

请先核验当前状态并提出新版精简矩阵的正式变更方案，不要启动求解。
```

## 19. 交接结论

阶段1–5的核心研究工作已经完成。阶段6当前真正需要解决的不是算法，而是
实验范围控制：用最少但充分的档位、预算、种子、策略和敏感性组合，构成
完整、可复现、不过度计算的论文证据链。

在新版矩阵受审前，保持暂停是正确状态。
