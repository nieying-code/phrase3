from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    ROOT
    / "docs"
    / "handoffs"
    / "2026-07-30_phase6_recourse_iis_audit.json"
)


def _expected_symbolic_label(pyomo_name: str) -> str:
    component, indices = pyomo_name.split("[", maxsplit=1)
    return f"{component}({indices[:-1].replace(',', '_')})"


def test_phase6_iis_files_match_audit_hashes_and_symbolic_mapping() -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    assert audit["iis_export"]["symbolic_solver_labels"] is True
    semantics = audit["iis_export"]["iis_minimal_semantics"]
    assert "irreducible" in semantics
    assert "does not claim minimum cardinality" in semantics
    assert len(audit["cases"]) == 3
    for case in audit["cases"]:
        iis_path = ROOT / case["iis_file"]
        payload = iis_path.read_bytes()
        assert hashlib.sha256(payload).hexdigest() == case[
            "iis_file_sha256"
        ]
        iis_text = payload.decode("utf-8")
        assert "x135:" not in iis_text
        constraints = case["iis_constraints"]
        bounds = case["iis_variable_lower_bounds"]
        assert len(constraints) == case["iis_constraint_count"]
        assert len(bounds) == case["iis_variable_lower_bound_count"]
        for row in (*constraints, *bounds):
            assert row["gurobi_name"] == _expected_symbolic_label(
                row["pyomo_name"]
            )
            assert row["gurobi_name"] in iis_text
        assert all(row["iis_lower_bound"] for row in bounds)
        assert not any(row["iis_upper_bound"] for row in bounds)


def test_phase6_iis_files_are_committed_as_byte_stable_artifacts() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "docs/handoffs/phase6_recourse_iis/*.ilp -text" in attributes
