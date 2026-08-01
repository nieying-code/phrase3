from __future__ import annotations

import json
from pathlib import Path
import subprocess

from src.phase6_environment import (
    environment_sha256,
    validate_locked_environment,
)
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
    assert fingerprints == {
        "scientific_config_sha256": _scientific_config_sha256(matrix),
        "e3_component_sha256": _e3_component_code_sha256(ROOT),
        "family_component_sha256": family_code_sha256(ROOT),
        "e3_runner_config_sha256": sha256_lf_text_file(
            ROOT / "configs" / "phase6_runner.yaml"
        ),
        "family_runner_config_sha256": family_runner_config_sha256(
            ROOT / "configs" / "phase6_family_runner.yaml"
        ),
        "environment_sha256": environment_sha256(
            validate_locked_environment(ROOT)
        ),
    }
    source = audit["source"]
    ancestor = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            source["validated_implementation_commit_sha"],
            "HEAD",
        ],
        cwd=ROOT,
        check=False,
    )
    assert ancestor.returncode == 0
    tree = subprocess.run(
        [
            "git",
            "show",
            "-s",
            "--format=%T",
            source["validated_implementation_commit_sha"],
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert tree == source["validated_implementation_tree_sha"]
    assert audit["experiment_execution"] == {
        "pilot_runs_started": 0,
        "formal_runs_started": 0,
        "scenario_generation_invoked": False,
        "gurobi_solve_invoked": False,
    }
