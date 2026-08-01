from __future__ import annotations

import ast
from pathlib import Path
import subprocess

import pytest

from src import phase6_environment, phase6_io, reproducibility
from src.phase6_environment import environment_sha256
from src.phase6_families import FAMILY_COMPONENT_FILES
from src.phase6_runner import PHASE6_E3_COMPONENT_FILES


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTROLLED_PATTERNS = (
    "*.py",
    "*.yaml",
    "*.yml",
    "requirements*.txt",
    ".gitattributes",
    ".gitignore",
)


def _tracked_controlled_files() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "--", *CONTROLLED_PATTERNS],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in completed.stdout.splitlines() if line]


def _direct_relative_imports(relative: str) -> set[str]:
    path = PROJECT_ROOT / relative
    if path.suffix != ".py":
        return set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    dependencies: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level <= 0:
            continue
        if not node.module:
            continue
        candidate = f"src/{node.module.split('.')[0]}.py"
        if (PROJECT_ROOT / candidate).is_file():
            dependencies.add(candidate)
    return dependencies


def test_controlled_checkout_files_are_declared_and_materialized_as_lf() -> None:
    files = _tracked_controlled_files()
    assert files
    attributes = subprocess.run(
        ["git", "check-attr", "text", "eol", "--", *files],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "eol: unspecified" not in attributes
    assert "eol: lf" in attributes
    for relative in files:
        assert b"\r" not in (PROJECT_ROOT / relative).read_bytes(), relative


def test_phase6_output_roots_are_git_ignored() -> None:
    completed = subprocess.run(
        [
            "git",
            "check-ignore",
            "outputs/phase6_clean_cycle/result.json",
            "outputs/gurobi_validation/result.json",
            "outputs/relative_complete_recourse_validation/result.json",
            "outputs/tmp/result.json",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert len(completed.stdout.splitlines()) == 4


def test_component_fingerprint_lists_cover_direct_local_dependencies() -> None:
    for components in (PHASE6_E3_COMPONENT_FILES, FAMILY_COMPONENT_FILES):
        assert ".gitignore" in components
        protected = set(components)
        missing = {
            relative: sorted(_direct_relative_imports(relative) - protected)
            for relative in components
            if _direct_relative_imports(relative) - protected
        }
        assert missing == {}


def test_lf_reader_rejects_crlf_controlled_input(tmp_path: Path) -> None:
    path = tmp_path / "controlled.yaml"
    path.write_bytes(b"status: frozen\r\n")
    with pytest.raises(RuntimeError, match="not LF-only"):
        phase6_io.read_lf_bytes(path)


def test_atomic_json_retries_only_transient_permission_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "result.json"
    real_replace = phase6_io.os.replace
    calls = 0

    def transient_replace(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise PermissionError("synthetic Windows sharing violation")
        real_replace(source, target)

    monkeypatch.setattr(phase6_io.os, "replace", transient_replace)
    monkeypatch.setattr(phase6_io, "sleep", lambda _: None)
    phase6_io.atomic_write_json(destination, {"message": "ok"})
    assert calls == 3
    assert b"\r" not in destination.read_bytes()


def test_exact_python_patch_is_checked_before_package_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(phase6_environment.sys, "version_info", (3, 12, 9))
    with pytest.raises(RuntimeError, match="requires Python 3.12.10"):
        phase6_environment.validate_locked_environment(PROJECT_ROOT)


def test_environment_fingerprint_changes_with_runtime_or_hardware() -> None:
    baseline = {
        "python_version": "3.12.10",
        "platform_machine": "AMD64",
        "total_memory_bytes": "1000",
    }
    changed_python = {**baseline, "python_version": "3.12.11"}
    changed_memory = {**baseline, "total_memory_bytes": "2000"}
    assert environment_sha256(baseline) != environment_sha256(changed_python)
    assert environment_sha256(baseline) != environment_sha256(changed_memory)


def test_execution_source_rejects_tracked_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reproducibility,
        "_git_metadata",
        lambda _: {
            "commit_sha": "a" * 40,
            "tree_sha": "b" * 40,
            "tracked_worktree_dirty": True,
            "untracked_paths": [],
        },
    )
    with pytest.raises(RuntimeError, match="tracked changes"):
        reproducibility.validate_execution_source(PROJECT_ROOT)


def test_execution_source_allows_only_untracked_output_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {
        "commit_sha": "a" * 40,
        "tree_sha": "b" * 40,
        "tracked_worktree_dirty": False,
        "untracked_paths": ["outputs/run/result.json"],
    }
    monkeypatch.setattr(reproducibility, "_git_metadata", lambda _: state)
    assert reproducibility.validate_execution_source(PROJECT_ROOT) == state
    state["untracked_paths"] = ["src/local_override.py"]
    with pytest.raises(RuntimeError, match="outside outputs"):
        reproducibility.validate_execution_source(PROJECT_ROOT)


def _initialize_execution_input_repository(path: Path) -> None:
    (path / "src").mkdir(parents=True)
    (path / "configs").mkdir()
    (path / "src" / "tracked.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    (path / "configs" / "base.yaml").write_text(
        "status: frozen\n",
        encoding="utf-8",
    )
    (path / ".gitignore").write_text("outputs/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "phase6-test@example.invalid"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Phase 6 Test"],
        cwd=path,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "test baseline"],
        cwd=path,
        check=True,
    )


@pytest.mark.parametrize(
    ("relative", "ignore_source"),
    [
        ("src/override.py", "repository"),
        ("configs/override.yaml", "repository"),
        ("src/override.py", "info_exclude"),
        ("configs/override.yaml", "global"),
        ("sitecustomize.py", "global"),
        ("gurobi.env", "repository"),
    ],
)
def test_execution_source_rejects_ignored_untracked_inputs(
    tmp_path: Path,
    relative: str,
    ignore_source: str,
) -> None:
    _initialize_execution_input_repository(tmp_path)
    if ignore_source == "repository":
        with (tmp_path / ".gitignore").open("a", encoding="utf-8") as handle:
            handle.write(f"{relative}\n")
        subprocess.run(
            ["git", "add", ".gitignore"],
            cwd=tmp_path,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "ignore override"],
            cwd=tmp_path,
            check=True,
        )
    elif ignore_source == "info_exclude":
        exclude = tmp_path / ".git" / "info" / "exclude"
        with exclude.open("a", encoding="utf-8") as handle:
            handle.write(f"{relative}\n")
    else:
        global_ignore = tmp_path / "global-ignore"
        global_ignore.write_text(f"{relative}\n", encoding="utf-8")
        subprocess.run(
            ["git", "config", "core.excludesFile", str(global_ignore)],
            cwd=tmp_path,
            check=True,
        )
    override = tmp_path / relative
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text("OVERRIDE = True\n", encoding="utf-8")
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", relative],
        cwd=tmp_path,
        check=False,
    )
    assert ignored.returncode == 0

    with pytest.raises(RuntimeError, match="including ignored files"):
        reproducibility.validate_execution_source(
            tmp_path,
            required_tracked_paths=(
                tmp_path / "src" / "tracked.py",
                tmp_path / "configs" / "base.yaml",
                tmp_path / ".gitignore",
            ),
        )


def test_execution_source_rejects_untracked_concrete_input(
    tmp_path: Path,
) -> None:
    _initialize_execution_input_repository(tmp_path)
    outside_roots = tmp_path / "local-runner.yaml"
    outside_roots.write_text("solver: gurobi\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="must be Git tracked"):
        reproducibility.validate_execution_source(
            tmp_path,
            required_tracked_paths=(outside_roots,),
        )
