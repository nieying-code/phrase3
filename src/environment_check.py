"""Report modeling packages and optionally solve tiny LP smoke tests."""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from typing import Any


PACKAGES = ("pyomo", "gurobipy", "highspy", "scipy", "numpy", "pandas", "yaml", "matplotlib")


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
        from scipy.optimize import linprog

        result = linprog(c=[1.0], bounds=[(1.0, None)], method="highs")
        tests["scipy_highs"] = {
            "available": True,
            "success": bool(result.success),
            "objective": float(result.fun) if result.success else None,
            "message": result.message,
        }
    except Exception as exc:  # diagnostic boundary
        tests["scipy_highs"] = {"available": False, "error": repr(exc)}

    try:
        import highspy

        highs = highspy.Highs()
        highs.setOptionValue("output_flag", False)
        highs.addVar(1.0, highspy.kHighsInf)
        highs.changeColCost(0, 1.0)
        highs.run()
        tests["highspy"] = {
            "available": True,
            "model_status": str(highs.getModelStatus()),
            "objective": float(highs.getObjectiveValue()),
        }
    except Exception as exc:  # diagnostic boundary
        tests["highspy"] = {"available": False, "error": repr(exc)}

    try:
        import gurobipy as gp

        model = gp.Model("license_smoke_test")
        model.Params.OutputFlag = 0
        model.addVar(lb=1.0, obj=1.0)
        model.ModelSense = gp.GRB.MINIMIZE
        model.optimize()
        tests["gurobi"] = {
            "available": True,
            "status": int(model.Status),
            "objective": float(model.ObjVal) if model.SolCount else None,
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
