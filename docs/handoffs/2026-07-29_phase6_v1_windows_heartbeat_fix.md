# Phase 6 V1 Windows Heartbeat Fix Handoff

## 任务目标

按精简版 Phase 6 实验矩阵，以 Gurobi-only 环境串行执行 V1
的三个 pilot 种子，并在发现工程失败后保留诊断、停止后续运行，
修复 Windows 心跳文件原子替换的瞬时文件锁问题。

## 分支和提交

- Branch: `agent/phase6-v1-streamlined-pilots`
- Base branch: `main`
- Base commit: `fb0c44a1dd2d183f5ea571441e0992f19b95d74d`
- Fix commit: `0f175efb6537709aecb3f7218ee72793a37cc623`
- PR: [#8](https://github.com/nieying-code/phrase3/pull/8)
- CI: pending

## Pilot 执行结果

所有运行均使用项目固定环境
`D:\新建文件夹\项目交付\阶段3-4修复同步\phrase3\.venv-gurobi`
并严格串行执行：

- Python 3.12.10；
- gurobipy 13.0.2；
- Gurobi Optimizer 13.0.2；
- Pyomo `gurobi_direct`；
- `Threads=1`；
- 未启用 HiGHS 或任何求解器回退。

### `pilot_streamlined_v1_2026072001`

- 状态：`optimal`；
- 完成预算：3/3；
- 冷/热算法执行：6/6 optimal；
- 冷热最大目标差：0.0。

### `pilot_streamlined_v1_2026072002`

- 状态：`optimal`；
- 完成预算：3/3；
- 冷/热算法执行：6/6 optimal；
- 冷热最大目标差：0.0。

### `pilot_streamlined_v1_2026072003`

- 终态：`worker_exception`；
- 完成预算：1/3；
- 第二个预算的 cold worker 失败；
- 第三个预算明确记录为
  `not_run_after_pair_sequence_failure`；
- 已完成预算的冷热目标差：0.0；
- 未使用同一个 run ID 重试，也未启动其他档位。

根因不是 Gurobi 数学求解失败。worker 在写 C&CG 迭代心跳时执行
`os.replace()`，遭遇 Windows 瞬时文件占用并抛出：

```text
PermissionError: [WinError 5] 拒绝访问
```

失败目标为：

```text
outputs/experiments/phase6/runs/
pilot_streamlined_v1_2026072003/workers/
a01_b01_cold_r01_progress.json
```

## 修改内容

### Windows 心跳文件

- `src/phase6_worker.py`
  - 原子替换遇到 `PermissionError` 时最多重试20次；
  - 每次间隔0.05秒，总等待上限约0.95秒；
  - 只重试 Windows 瞬时权限错误，其他异常继续直接暴露；
  - 无论成功或失败均尽力清理临时文件。

### 前置失败摘要

- `src/run_phase6.py`
  - 配置加载或正式运行前置检查失败时，除
    `runner_exception.json` 外同步生成受限字段的
    `status_summary.json`；
  - 后续状态查询不需要解析大型诊断或结果文件。

### 测试

- `tests/test_phase6_worker.py`
  - 模拟前两次 `os.replace()` 抛出 `PermissionError`、
    第三次成功；
  - 验证最终 JSON 正确且无临时文件残留。
- `tests/test_run_phase6.py`
  - 验证配置加载失败也生成小型状态摘要。

## 验证结果

实际执行：

```text
.\.venv-gurobi\Scripts\python.exe -m pytest \
  tests\test_phase6_worker.py tests\test_run_phase6.py \
  tests\test_phase6_status.py -q
```

结果：`6 passed in 1.22s`。

完整回归：

```text
.\.venv-gurobi\Scripts\python.exe -m pytest -q
```

结果：`83 passed in 34.42s`。

`git diff --check` 未发现空白错误，仅有 Windows 工作树的
LF/CRLF 提示。

## 结果有效性与重跑边界

两个成功运行和一个失败运行均保留为诊断证据，不删除、不覆盖。
本修复修改了 `src/phase6_worker.py`，因此 E3 组件哈希会变化：

- 修复前两个成功 V1 pilot 不得计入修复后的正式计算门槛；
- 失败 run ID 是不可变终态，禁止恢复为成功；
- 本 PR 合并后，三个 V1 pilot 都必须使用全新 run ID 串行重跑；
- 当前不得运行 formal seeds、V2、P1、P2、P3 或 P4。

## 风险点

ChatGPT 复审时请重点检查：

1. 重试范围是否严格限于 `PermissionError`；
2. 重试是否有明确次数和时间上限；
3. 临时文件清理是否会掩盖原始替换异常；
4. 前置异常摘要是否保持小型、白名单字段；
5. 组件哈希变化后是否正确要求重跑全部 V1 pilot；
6. 是否遵守失败 run ID 不可变和不得自动重试规则。

## 下一步建议

1. ChatGPT 审查并由用户合并本 PR；
2. 从最新 `main` 创建新的 pilot 分支；
3. 使用三个全新 run ID 严格串行重跑 V1；
4. 核验3/3种子、每个种子3/3预算、冷热目标一致和环境指纹；
5. 再决定是否进入精简矩阵的后续执行器与 pilot 工作。
