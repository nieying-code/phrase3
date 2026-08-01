"""Strict software and hardware identity for Phase 6 execution."""

from __future__ import annotations

from importlib import metadata
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys

import gurobipy
import psutil


REQUIRED_PYTHON_VERSION = (3, 12, 10)
REQUIRED_PYTHON_IMPLEMENTATION = "CPython"
REQUIRED_GUROBI_VERSION = (13, 0, 2)
PHASE6_REQUIREMENTS_FILE = "requirements-gurobi-lock.txt"


def environment_sha256(environment: dict[str, str]) -> str:
    encoded = json.dumps(
        dict(sorted(environment.items())),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_locked_environment(project_root: Path) -> dict[str, str]:
    """Validate the complete locked runtime and return its exact identity."""

    actual_python = tuple(sys.version_info[:3])
    if actual_python != REQUIRED_PYTHON_VERSION:
        raise RuntimeError(
            "Phase 6 requires Python "
            f"{'.'.join(map(str, REQUIRED_PYTHON_VERSION))}; found "
            f"{platform.python_version()}"
        )
    implementation = platform.python_implementation()
    if implementation != REQUIRED_PYTHON_IMPLEMENTATION:
        raise RuntimeError(
            f"Phase 6 requires {REQUIRED_PYTHON_IMPLEMENTATION}; "
            f"found {implementation}"
        )
    optimizer_version = tuple(gurobipy.gurobi.version())
    if optimizer_version != REQUIRED_GUROBI_VERSION:
        raise RuntimeError(
            "Phase 6 requires Gurobi Optimizer "
            f"{'.'.join(map(str, REQUIRED_GUROBI_VERSION))}; found "
            f"{'.'.join(map(str, optimizer_version))}"
        )

    lock_path = project_root / PHASE6_REQUIREMENTS_FILE
    expected: dict[str, tuple[str, str]] = {}
    for raw in lock_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line or any(token in line for token in (";", "[", "]")):
            raise RuntimeError(f"non-exact requirement in {lock_path}: {line}")
        name, version = (part.strip() for part in line.split("==", 1))
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        expected[normalized] = (name, version)

    packages: dict[str, str] = {}
    mismatches: list[str] = []
    for normalized, (name, required) in sorted(expected.items()):
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            installed = "not-installed"
        packages[normalized] = installed
        if installed != required:
            mismatches.append(f"{name}: required {required}, found {installed}")
    if mismatches:
        raise RuntimeError(
            "Phase 6 locked environment mismatch: " + "; ".join(mismatches)
        )

    return {
        "python_version": platform.python_version(),
        "python_implementation": implementation,
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "processor": platform.processor() or os.environ.get(
            "PROCESSOR_IDENTIFIER", "unknown"
        ),
        "physical_cpu_count": str(psutil.cpu_count(logical=False)),
        "logical_cpu_count": str(psutil.cpu_count(logical=True)),
        "total_memory_bytes": str(psutil.virtual_memory().total),
        "gurobi_optimizer_version": ".".join(map(str, optimizer_version)),
        **{f"package:{name}": version for name, version in packages.items()},
    }
