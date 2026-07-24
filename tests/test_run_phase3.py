from __future__ import annotations

import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

import pytest

import src.run_phase3 as run_phase3_module
from src.run_phase3 import run


def test_formal_run_enforces_acceptance_and_writes_reproducibility(
    tmp_path: Path,
) -> None:
    payload = run(Path("configs/phase3.yaml"), tmp_path)

    assert payload["status"] == "accepted"
    assert payload["acceptance"]["passed"]
    assert payload["acceptance"]["failed_checks"] == []
    assert payload["acceptance"]["objective_difference"] == pytest.approx(0.0)
    assert payload["extensive"]["status"] == "optimal"
    assert payload["ccg"]["converged"]
    assert payload["ccg"]["termination_status"] == "optimal"

    reproducibility_root = tmp_path / "reproducibility" / "phase3"
    config_path = reproducibility_root / "resolved_config.json"
    scenarios_path = reproducibility_root / "training_scenarios.csv"
    manifest_path = reproducibility_root / "manifest.json"
    for path in (config_path, scenarios_path, manifest_path):
        assert path.is_file()
        assert path.stat().st_size > 0

    resolved_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert resolved_config["project"]["seed"] == 20260723

    with scenarios_path.open(encoding="utf-8-sig", newline="") as handle:
        scenario_rows = list(csv.DictReader(handle))
    assert len(scenario_rows) == 20 * 1 * 4

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["scenario_generator_version"] == "1.0"
    assert manifest["packages"]["pyomo"]
    assert manifest["packages"]["highspy"]
    assert manifest["solver"]["selected"] in {"appsi_highs", "highs"}
    assert manifest["formal_acceptance"]["passed"]
    assert manifest["scenarios_sha256"] == hashlib.sha256(
        scenarios_path.read_bytes()
    ).hexdigest()
    assert len(manifest["resolved_config_sha256"]) == 64

    ccg_payload = json.loads(
        (
            tmp_path / "solutions" / "phase3" / "ccg_solution.json"
        ).read_text(encoding="utf-8")
    )
    assert ccg_payload["formal_acceptance"]["passed"]
    assert (
        ccg_payload["reproducibility"]["scenarios_sha256"]
        == manifest["scenarios_sha256"]
    )


def test_main_exits_nonzero_when_ccg_does_not_converge(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original = run_phase3_module.run_standard_ccg

    def force_oracle_failure(*args, **kwargs):
        result = original(*args, **kwargs)
        return replace(
            result,
            converged=False,
            termination_status="oracle_failure",
        )

    monkeypatch.setattr(
        run_phase3_module,
        "run_standard_ccg",
        force_oracle_failure,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_phase3",
            "--config",
            "configs/phase3.yaml",
            "--output",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit, match="formal acceptance failed"):
        run_phase3_module.main()

    ccg_payload = json.loads(
        (
            tmp_path / "solutions" / "phase3" / "ccg_solution.json"
        ).read_text(encoding="utf-8")
    )
    assert not ccg_payload["formal_acceptance"]["passed"]
    assert "ccg_converged" in ccg_payload["formal_acceptance"][
        "failed_checks"
    ]
    assert "ccg_termination_optimal" in ccg_payload[
        "formal_acceptance"
    ]["failed_checks"]
