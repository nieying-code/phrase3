# Repository Execution Rules

These rules apply to every Codex task in this repository.

## Python environment

- Use only:
  `D:\新建文件夹\项目交付\阶段3-4修复同步\phrase3\.venv-gurobi\Scripts\python.exe`
- PyCharm must use the same interpreter.
- Do not use the Codex-managed Python runtime, the system base interpreter,
  `D:\Tools\Python312\python.exe`, or `D:\pycharm.projects\.venv`.
- Install and reproduce dependencies from `requirements-gurobi-lock.txt`.

## Solver

- Use only Gurobi Optimizer 13.0.2 through `gurobipy==13.0.2` and Pyomo
  `gurobi_direct`.
- Use one solver thread (`Threads=1`) for experiment comparability.
- Never use HiGHS, `highspy`, or an automatic solver fallback.
- Run the repository Gurobi runtime preflight before experiments.

## Phase 6 monitoring

- Never parse or print Phase 6 `result.json` or `checkpoint.json` with
  PowerShell `ConvertFrom-Json`.
- Never print a complete result, checkpoint, worker result, scenario-cost map,
  or iteration history to the terminal.
- Use `python -m src.phase6_status --output outputs --run-id <RUN_ID>` for a
  bounded run summary.
- Inspect large files through file size, compact CSV rows, or bounded Python
  field extraction only.
- Keep pilots serial and preserve failed/timeout runs under immutable run IDs.
- P3 and P4 were removed from the streamlined Phase 6 matrix and must not be
  reintroduced or run without an explicitly reviewed matrix revision.
- Do not run formal seeds without explicit authorization.
