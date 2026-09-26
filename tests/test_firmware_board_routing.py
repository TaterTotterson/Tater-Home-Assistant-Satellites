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
    def test_thirdreality_target_aliases_share_one_manifest_key(self) -> None:
        keys = _constant_mapping("BOARD_MANIFEST_KEYS")
        labels = _constant_mapping("BOARD_LABELS")

        self.assertEqual(keys["thirdreality_s420"], "thirdreality_s420")
        self.assertEqual(keys["thirdreality-s420"], "thirdreality_s420")
        self.assertEqual(keys["s420"], "thirdreality_s420")
        self.assertIn("ThirdReality", labels["thirdreality_s420"])

    def test_echo_targets_have_distinct_manifest_keys_and_labels(self) -> None:
        keys = _constant_mapping("BOARD_MANIFEST_KEYS")
        labels = _constant_mapping("BOARD_LABELS")

        self.assertEqual(keys["biscuit"], "biscuit")
        self.assertEqual(keys["echo-dot-2"], "biscuit")
        self.assertEqual(keys["checkers"], "checkers")
        self.assertEqual(keys["echo-show-5"], "checkers")
        self.assertIn("Echo Dot 2", labels["biscuit"])
        self.assertIn("Echo Show 5", labels["checkers"])

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
