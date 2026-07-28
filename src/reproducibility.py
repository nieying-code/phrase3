"""Reproducibility metadata for formal experiment runs."""

from __future__ import annotations

import hashlib
from importlib import metadata
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any, Iterable, Mapping

import psutil

from .model_common import select_solver
from .scenario_generator import SCENARIO_GENERATOR_VERSION


PACKAGE_NAMES = (
    "pyomo",
    "gurobipy",
    "numpy",
    "pandas",
    "PyYAML",
    "matplotlib",
    "psutil",
    "filelock",
    "pytest",
)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in PACKAGE_NAMES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _git_metadata(project_root: Path) -> dict[str, Any]:
    command = ["git", "-C", str(project_root)]
    try:
        commit = subprocess.run(
            [*command, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            [*command, "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return {
            "commit_sha": commit,
            "working_tree_dirty": bool(status.strip()),
        }
    except (OSError, subprocess.CalledProcessError) as exc:
        return {
            "commit_sha": None,
            "working_tree_dirty": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _solver_metadata(
    preference: Iterable[str],
    *,
    solver_threads: int | None,
) -> dict[str, Any]:
    requested = tuple(str(name) for name in preference)
    try:
        solver_name, solver = select_solver(requested)
        version = solver.version()
        if isinstance(version, tuple):
            version = ".".join(str(part) for part in version)
        elif version is not None:
            version = str(version)
        return {
            "preference": list(requested),
            "selected": solver_name,
            "version": version,
            "threads": solver_threads,
        }
    except Exception as exc:
        return {
            "preference": list(requested),
            "selected": None,
            "version": None,
            "threads": solver_threads,
            "error": f"{type(exc).__name__}: {exc}",
        }


def capture_runtime_context(
    *,
    solver_preference: Iterable[str],
    project_root: Path,
    solver_threads: int | None = None,
) -> dict[str, Any]:
    """Capture versions and source state before output files are created."""

    return {
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "hardware": {
            "machine": platform.machine(),
            "processor": platform.processor(),
            "physical_cpu_count": psutil.cpu_count(logical=False),
            "logical_cpu_count": os.cpu_count(),
            "total_memory_bytes": psutil.virtual_memory().total,
        },
        "packages": _package_versions(),
        "solver": _solver_metadata(
            solver_preference,
            solver_threads=solver_threads,
        ),
        "git": _git_metadata(project_root),
    }


def build_reproducibility_manifest(
    *,
    config_path: Path,
    resolved_config_path: Path,
    scenarios_path: Path,
    runtime_context: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a machine-readable manifest for one formal run."""

    return {
        "source_config_path": str(config_path),
        "resolved_config_path": str(resolved_config_path),
        "resolved_config_sha256": sha256_file(resolved_config_path),
        "scenarios_path": str(scenarios_path),
        "scenarios_sha256": sha256_file(scenarios_path),
        "scenario_generator_version": SCENARIO_GENERATOR_VERSION,
        **runtime_context,
    }
