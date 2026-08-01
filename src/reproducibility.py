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

PHASE6_EXECUTION_INPUT_ROOTS = (
    "src",
    "configs",
)
PHASE6_ROOT_EXECUTION_INPUT_PATHSPECS = (
    ":(top,glob)*.py",
    ":(top,glob)*.pyw",
    ":(top,glob)*.pyd",
    ":(top,glob)*.yaml",
    ":(top,glob)*.yml",
    ":(top)gurobi.env",
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
        tree = subprocess.run(
            [*command, "rev-parse", "HEAD^{tree}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        tracked_status = subprocess.run(
            [*command, "status", "--porcelain", "--untracked-files=no"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        untracked_output = subprocess.run(
            [*command, "ls-files", "--others", "--exclude-standard", "-z"],
            check=True,
            capture_output=True,
        ).stdout
        untracked_paths = [
            value.decode("utf-8", errors="replace")
            for value in untracked_output.split(b"\0")
            if value
        ]
        return {
            "commit_sha": commit,
            "tree_sha": tree,
            "tracked_worktree_dirty": bool(tracked_status.strip()),
            "untracked_paths": untracked_paths,
            "working_tree_dirty": bool(
                tracked_status.strip() or untracked_paths
            ),
        }
    except (OSError, subprocess.CalledProcessError) as exc:
        return {
            "commit_sha": None,
            "working_tree_dirty": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _git_untracked_execution_inputs(project_root: Path) -> list[str]:
    """List untracked execution inputs, including files hidden by ignores."""

    completed = subprocess.run(
        [
            "git",
            "-C",
            str(project_root),
            "ls-files",
            "--others",
            "-z",
            "--",
            *PHASE6_EXECUTION_INPUT_ROOTS,
            *PHASE6_ROOT_EXECUTION_INPUT_PATHSPECS,
        ],
        check=True,
        capture_output=True,
    )
    candidates = [
        value.decode("utf-8", errors="replace")
        for value in completed.stdout.split(b"\0")
        if value
    ]
    return [
        value
        for value in candidates
        if "__pycache__/" not in value
        and not value.endswith((".pyc", ".pyo"))
    ]


def _require_git_tracked_files(
    project_root: Path,
    paths: Iterable[Path],
) -> list[str]:
    """Require every concrete Phase 6 input to be tracked by this repository."""

    relative_paths: list[str] = []
    root = project_root.resolve()
    for path in paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise RuntimeError(
                f"Phase 6 execution input is outside the repository: {resolved}"
            ) from exc
        if not resolved.is_file():
            raise RuntimeError(f"Phase 6 execution input is missing: {relative}")
        relative_paths.append(relative)
    if not relative_paths:
        return []
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(project_root),
            "ls-files",
            "--error-unmatch",
            "--",
            *relative_paths,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    tracked = set(completed.stdout.splitlines())
    missing = [path for path in relative_paths if path not in tracked]
    if completed.returncode or missing:
        details = missing or relative_paths
        raise RuntimeError(
            "Phase 6 execution inputs must be Git tracked: "
            + ", ".join(details[:20])
        )
    return relative_paths


def validate_execution_source(
    project_root: Path,
    *,
    required_tracked_paths: Iterable[Path] = (),
) -> dict[str, Any]:
    """Require committed, tracked inputs and only controlled output artifacts."""

    state = _git_metadata(project_root)
    if state.get("commit_sha") is None or state.get("tree_sha") is None:
        raise RuntimeError(f"Phase 6 Git metadata unavailable: {state}")
    if state.get("tracked_worktree_dirty"):
        raise RuntimeError(
            "Phase 6 pilot/formal execution requires no staged or unstaged "
            "tracked changes"
        )
    try:
        untracked_execution_inputs = _git_untracked_execution_inputs(
            project_root
        )
        tracked_execution_inputs = _require_git_tracked_files(
            project_root,
            required_tracked_paths,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            f"Phase 6 Git execution-input validation failed: {exc}"
        ) from exc
    if untracked_execution_inputs:
        raise RuntimeError(
            "Phase 6 execution found untracked source/config inputs, including "
            "ignored files: " + ", ".join(untracked_execution_inputs[:20])
        )
    unexpected = [
        value
        for value in state.get("untracked_paths", [])
        if value != "outputs" and not value.startswith("outputs/")
    ]
    if unexpected:
        raise RuntimeError(
            "Phase 6 execution found untracked paths outside outputs/: "
            + ", ".join(unexpected[:20])
        )
    state["untracked_execution_input_paths"] = []
    state["tracked_execution_input_paths"] = tracked_execution_inputs
    return state


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
