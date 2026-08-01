from __future__ import annotations

import json
from pathlib import Path

from src.phase6_environment import environment_sha256
from src.phase6_families import (
    family_code_sha256,
    scientific_config_sha256,
)
from src.phase6_family_runner import family_runner_config_sha256
from src.phase6_io import sha256_lf_text_file
from src.phase6_protocol import load_phase6_matrix
from src.phase6_runner import (
    _e3_component_code_sha256,
    _scientific_config_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    ROOT
    / "docs"
    / "handoffs"
    / "2026-08-01_phase6_reproducibility_hardening_audit.json"
)


def test_reproducibility_hardening_audit_matches_current_execution_inputs() -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    matrix_path = ROOT / "configs" / "phase6_experiment_matrix.yaml"
    matrix = load_phase6_matrix(matrix_path)
    fingerprints = audit["fingerprints"]

    assert _scientific_config_sha256(matrix) == scientific_config_sha256(
        matrix
    )
    assert {
        key: value
        for key, value in fingerprints.items()
        if key != "environment_sha256"
    } == {
        "scientific_config_sha256": _scientific_config_sha256(matrix),
        "e3_component_sha256": _e3_component_code_sha256(ROOT),
        "family_component_sha256": family_code_sha256(ROOT),
        "e3_runner_config_sha256": sha256_lf_text_file(
            ROOT / "configs" / "phase6_runner.yaml"
        ),
        "family_runner_config_sha256": family_runner_config_sha256(
            ROOT / "configs" / "phase6_family_runner.yaml"
        ),
    }
    assert environment_sha256(audit["environment_identity"]) == (
        fingerprints["environment_sha256"]
    )
    assert audit["source"]["identity_rule"].startswith("final PR head")
    assert audit["source"]["execution_input_roots"] == ["src", "configs"]
    assert set(audit["source"]["root_execution_input_patterns"]) == {
        "*.py",
        "*.pyw",
        "*.pyd",
        "*.yaml",
        "*.yml",
        "gurobi.env",
    }
    assert audit["source"]["ignored_untracked_execution_inputs_rejected"]
    assert audit["source"]["required_concrete_inputs_must_be_git_tracked"]
    assert set(audit["source"]["ignore_sources_covered"]) == {
        "repository_gitignore",
        "git_info_exclude",
        "user_global_ignore",
    }
    assert audit["validation"]["github_actions"] != "pending"
    assert audit["experiment_execution"] == {
        "pilot_runs_started": 0,
        "formal_runs_started": 0,
        "scenario_generation_invoked": False,
        "gurobi_solve_invoked": False,
    }
