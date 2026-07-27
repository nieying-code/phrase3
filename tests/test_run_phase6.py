import json
from pathlib import Path

from src.run_phase6 import run


def test_missing_runner_config_writes_minimum_diagnostic(
    tmp_path: Path,
) -> None:
    result = run(
        config_path=tmp_path / "missing.yaml",
        output_root=tmp_path / "outputs",
        tier_id="V1",
        seed=2026072001,
        execution_mode="pilot",
        run_id="missing_config",
    )

    assert result["status"] == "runner_exception"
    assert result["failure"]["stage"] == "runner_config_load"
    assert result["completed_budget_count"] == 0
    diagnostic = (
        tmp_path
        / "outputs"
        / "experiments"
        / "phase6"
        / "runs"
        / "missing_config"
        / "runner_exception.json"
    )
    assert diagnostic.exists()
    saved = json.loads(diagnostic.read_text(encoding="utf-8"))
    assert saved["failure"]["exception_type"] == "FileNotFoundError"
