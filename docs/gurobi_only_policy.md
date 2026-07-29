# Gurobi-only求解策略

自2026-07-28起，本项目的开发、测试、pilot和正式实验只允许：

```text
gurobipy 13.0.2
Gurobi Optimizer 13.0.2
Pyomo gurobi_direct
Threads = 1
```

`solver_preference`必须严格等于`("gurobi",)`。代码同时核验
`gurobipy`发行版和实际加载的Optimizer版本；版本不符时在场景生成前
失败。禁止HiGHS、其他求解器名称和自动回退。

正式环境：

```text
D:\新建文件夹\项目交付\阶段3-4修复同步\phrase3\.venv-gurobi\Scripts\python.exe
```

许可证文件不得提交Git。所有正式计时使用单线程和串行runner。

## 历史结果边界

阶段1–5的历史HiGHS验证继续保留，不改写历史handoff；但HiGHS运行时间、
迭代和吞吐量不得进入Gurobi正式统计。

阶段3/4扩展式与标准C&CG、阶段5冷/热算法已经用Gurobi进行代表性交叉
验证。阶段6正式种子尚未开始。

精简阶段6矩阵仍要求：

```text
V1/V2/P1/P2 × 3 pilot seeds = 12条当前指纹pilot
```

但V1–P2每条序列已由六个预算缩减为三个预算，且除V2外只执行一次技术
重复。只有当前矩阵、runner、E3代码和`.venv-gurobi`环境生成的pilot，
以及完整的计算量投影和推进门槛通过后，才能授权正式实验。
