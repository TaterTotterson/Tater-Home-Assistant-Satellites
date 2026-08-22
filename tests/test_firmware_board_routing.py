from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONST_PATH = ROOT / "custom_components" / "tater_satellite" / "const.py"


def _constant_mapping(name: str) -> dict[str, str]:
    module = ast.parse(CONST_PATH.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if isinstance(node.target, ast.Name) and node.target.id == name:
            value = ast.literal_eval(node.value)
            assert isinstance(value, dict)
            return value
    raise AssertionError(f"Missing {name}")


class FirmwareBoardRoutingTests(unittest.TestCase):
    def test_sat1_production_and_beta_use_distinct_manifest_keys(self) -> None:
        keys = _constant_mapping("BOARD_MANIFEST_KEYS")
        self.assertEqual(keys["satellite1"], "satellite1")
        self.assertEqual(
            keys["satellite1-beta-rev41"],
            "satellite1_beta_rev41",
        )
        self.assertNotEqual(
            keys["satellite1"],
            keys["satellite1-beta-rev41"],
        )

    def test_sat1_beta_has_an_explicit_catalog_label(self) -> None:
        labels = _constant_mapping("BOARD_LABELS")
        self.assertEqual(
            labels["satellite1_beta_rev41"],
            "Satellite1 Beta.1 / rev4.1",
        )


if __name__ == "__main__":
    unittest.main()
