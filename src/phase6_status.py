"""Print a bounded Phase 6 run summary without expanding large result JSON."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from typing import Any, Mapping

import psutil


MAX_SUMMARY_BYTES = 16_384


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return payload


def _registry_row(base: Path, run_id: str) -> dict[str, str] | None:
    path = base / "run_registry.csv"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("run_id") == run_id:
                return dict(row)
    return None


def _matching_processes(run_id: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    current_pid = psutil.Process().pid
    for process in psutil.process_iter(
        ("pid", "name", "cmdline", "memory_info")
    ):
        try:
            if process.pid == current_pid:
                continue
            command = " ".join(process.info.get("cmdline") or ())
            normalized = command.replace("\\", "/").lower()
            is_phase6_runner = (
                "-m src.run_phase6" in normalized
                or "/src/run_phase6.py" in normalized
            )
            if run_id not in command or not is_phase6_runner:
                continue
            memory = process.info.get("memory_info")
            matches.append(
                {
                    "pid": process.pid,
                    "name": process.info.get("name"),
                    "rss_mb": (
                        round(memory.rss / (1024 * 1024), 3)
                        if memory is not None
                        else None
                    ),
                }
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return matches


def _result_metrics(result: Mapping[str, Any]) -> dict[str, Any]:
    comparisons = list(result.get("comparisons") or ())
    comparison_statuses = Counter(
        str(item.get("status", "unknown")) for item in comparisons
    )
    algorithm_statuses: Counter[str] = Counter()
    solvers: set[str] = set()
    objective_differences: list[float] = []
    performance_rows = 0
    for comparison in comparisons:
        difference = comparison.get("objective_difference")
        if isinstance(difference, (int, float)):
            objective_differences.append(abs(float(difference)))
        repetitions = int(comparison.get("planned_repetitions", 0))
        for algorithm in ("cold", "warm"):
            algorithm_payload = comparison.get(algorithm) or {}
            actual = list(algorithm_payload.get("repetitions") or ())
            performance_rows += max(repetitions, len(actual))
            for repetition in actual:
                algorithm_statuses[str(repetition.get("status", "unknown"))] += 1
                ccg_result = repetition.get("ccg_result") or {}
                solver = ccg_result.get("solver")
                if solver:
                    solvers.add(str(solver))
    return {
        "comparison_count": len(comparisons),
        "comparison_status_counts": dict(sorted(comparison_statuses.items())),
        "algorithm_status_counts": dict(sorted(algorithm_statuses.items())),
        "planned_performance_rows": performance_rows,
        "max_abs_objective_difference": (
            max(objective_differences) if objective_differences else None
        ),
        "solvers": sorted(solvers),
    }


def summarize_run(
    output_root: Path,
    run_id: str,
    *,
    inspect_processes: bool = True,
) -> dict[str, Any]:
    """Return only bounded metadata for one run."""

    base = output_root.resolve() / "experiments" / "phase6"
    run_directory = base / "runs" / run_id
    candidates = (
        ("result", run_directory / "result.json"),
        ("checkpoint", run_directory / "checkpoint.json"),
        ("runner_exception", run_directory / "runner_exception.json"),
    )
    files = {
        name: {
            "path": str(path),
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else None,
        }
        for name, path in candidates
    }
    registry = _registry_row(base, run_id)
    source_name = next(
        (name for name, path in candidates if path.exists()),
        None,
    )
    payload: dict[str, Any] = {}
    read_error = None
    if source_name is not None:
        source_path = dict(candidates)[source_name]
        try:
            payload = _read_json(source_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            read_error = f"{type(exc).__name__}: {exc}"

    manifest_path = run_directory / "manifest.json"
    runtime: dict[str, Any] | None = None
    if manifest_path.exists():
        try:
            manifest = _read_json(manifest_path)
            runtime = {
                "python": (manifest.get("python") or {}).get("version"),
                "python_executable": (
                    manifest.get("python") or {}
                ).get("executable"),
                "gurobipy": (
                    manifest.get("packages") or {}
                ).get("gurobipy"),
                "solver": (manifest.get("solver") or {}).get("selected"),
                "optimizer": (manifest.get("solver") or {}).get("version"),
                "threads": (manifest.get("solver") or {}).get("threads"),
            }
        except (OSError, ValueError, json.JSONDecodeError):
            runtime = {"manifest_status": "unreadable"}

    summary = {
        "run_id": run_id,
        "run_directory": str(run_directory),
        "source": source_name,
        "status": payload.get(
            "status",
            registry.get("status") if registry else "not_found",
        ),
        "tier_id": payload.get(
            "tier_id",
            registry.get("tier_id") if registry else None,
        ),
        "seed": payload.get(
            "seed",
            registry.get("seed") if registry else None,
        ),
        "planned_budget_count": payload.get(
            "planned_budget_count",
            registry.get("planned_budget_count") if registry else None,
        ),
        "completed_budget_count": payload.get(
            "completed_budget_count",
            registry.get("completed_budget_count") if registry else None,
        ),
        "failure": payload.get("failure"),
        "metrics": _result_metrics(payload),
        "runtime": runtime,
        "processes": (
            _matching_processes(run_id) if inspect_processes else []
        ),
        "files": files,
        "read_error": read_error,
    }
    return summary


def render_summary(summary: Mapping[str, Any]) -> str:
    """Serialize a status summary and enforce a hard output-size ceiling."""

    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    if len(rendered.encode("utf-8")) > MAX_SUMMARY_BYTES:
        raise ValueError("Phase 6 status summary exceeded its safety limit")
    return rendered


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--no-process-scan",
        action="store_true",
        help="Skip the read-only process command-line scan",
    )
    args = parser.parse_args()
    summary = summarize_run(
        args.output,
        args.run_id,
        inspect_processes=not args.no_process_scan,
    )
    print(render_summary(summary))


if __name__ == "__main__":
    main()
