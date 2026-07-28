"""Report modeling packages and optionally solve tiny LP smoke tests."""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from typing import Any


PACKAGES = ("pyomo", "gurobipy", "numpy", "pandas", "yaml", "matplotlib")


def package_status(name: str) -> dict[str, Any]:
    spec = importlib.util.find_spec(name)
    status: dict[str, Any] = {"installed": spec is not None}
    if spec is not None:
        module = __import__(name)
        status["version"] = getattr(module, "__version__", "unknown")
    return status


def run_smoke_tests() -> dict[str, Any]:
    tests: dict[str, Any] = {}
    try:
        import gurobipy as gp

        model = gp.Model("license_smoke_test")
        model.Params.OutputFlag = 0
        model.Params.Threads = 1
        model.addVar(lb=1.0, obj=1.0)
        model.ModelSense = gp.GRB.MINIMIZE
        model.optimize()
        tests["gurobi"] = {
            "available": True,
            "status": int(model.Status),
            "objective": float(model.ObjVal) if model.SolCount else None,
            "threads": int(model.Params.Threads),
        }
    except Exception as exc:  # diagnostic boundary
        tests["gurobi"] = {"available": False, "error": repr(exc)}
    return tests


def build_report(smoke_test: bool) -> dict[str, Any]:
    report: dict[str, Any] = {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "packages": {name: package_status(name) for name in PACKAGES},
    }
    if smoke_test:
        report["solver_smoke_tests"] = run_smoke_tests()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true", help="solve one-variable LPs when solvers exist")
    args = parser.parse_args()
    print(json.dumps(build_report(args.smoke_test), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
