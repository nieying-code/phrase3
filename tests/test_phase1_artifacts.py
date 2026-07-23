from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.parameters import BudgetAllocation, ModelDimensions


class TestPhase1Artifacts(unittest.TestCase):
    def test_required_documents_exist_and_are_substantive(self) -> None:
        required = [
            "literature_review.md",
            "research_design.md",
            "mathematical_model.md",
            "algorithm.md",
            "experiment_design.md",
            "project_plan.md",
            "phase1_completion_report.md",
        ]
        for name in required:
            path = ROOT / "docs" / name
            self.assertTrue(path.is_file(), name)
            self.assertGreater(len(path.read_text(encoding="utf-8")), 1000, name)

    def test_base_config_contains_reproducibility_controls(self) -> None:
        text = (ROOT / "configs" / "base.yaml").read_text(encoding="utf-8")
        for token in ("seed:", "max_iterations:", "absolute_tolerance:", "solver:", "fifo_mode:"):
            self.assertIn(token, text)

    def test_dimensions_validate(self) -> None:
        dims = ModelDimensions(items=1, periods=4, scenarios=20, shelf_life=3)
        dims.validate()
        with self.assertRaises(ValueError):
            ModelDimensions(items=1, periods=0, scenarios=20, shelf_life=3).validate()

    def test_residual_budget_defines_reserve(self) -> None:
        allocation = BudgetAllocation(total_budget=100.0, regular_commitment=65.0)
        self.assertAlmostEqual(allocation.reserve, 35.0)
        self.assertAlmostEqual(allocation.reserve_ratio, 0.35)

    def test_mathematical_model_records_key_guards(self) -> None:
        text = (ROOT / "docs" / "mathematical_model.md").read_text(encoding="utf-8")
        for token in ("预算可识别性", "FIFO", "完整场景扩展式", "应急采购预算", "不可行补救"):
            self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
