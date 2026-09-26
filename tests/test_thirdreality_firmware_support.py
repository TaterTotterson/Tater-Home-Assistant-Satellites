from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_PATH = ROOT / "custom_components" / "tater_satellite" / "firmware.py"
CONST_PATH = ROOT / "custom_components" / "tater_satellite" / "const.py"
PANEL_PATH = (
    ROOT
    / "custom_components"
    / "tater_satellite"
    / "frontend"
    / "tater-satellite-panel.js"
)


def _constant(name: str) -> Any:
    module = ast.parse(CONST_PATH.read_text(encoding="utf-8"))
    for node in module.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"Missing {name}")


def _thirdreality_normalizer():
    module = ast.parse(FIRMWARE_PATH.read_text(encoding="utf-8"))
    names = {
        "_SHA256",
        "_VERSION",
        "board_manifest_key",
        "display_version",
        "normalize_thirdreality_manifest",
    }
    selected = []
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in names
            for target in node.targets
        ):
            selected.append(node)
        elif (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in names
        ):
            selected.append(node)
    namespace = {
        "Any": Any,
        "re": re,
        "BOARD_LABELS": _constant("BOARD_LABELS"),
        "BOARD_MANIFEST_KEYS": _constant("BOARD_MANIFEST_KEYS"),
        "THIRDREALITY_FIRMWARE_RELEASE_URL": _constant(
            "THIRDREALITY_FIRMWARE_RELEASE_URL"
        ),
        "THIRDREALITY_FIRMWARE_URL": _constant("THIRDREALITY_FIRMWARE_URL"),
    }
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(FIRMWARE_PATH), "exec"),
        namespace,
    )
    return namespace["normalize_thirdreality_manifest"]


def _thirdreality_manifest() -> dict[str, Any]:
    return {
        "schema": 1,
        "version": "0.2.20",
        "display_version": "0.2.20",
        "devices": [
            {
                "key": "thirdreality_s420",
                "label": "Tater ThirdReality S420",
                "board": "thirdreality_s420",
                "firmware_version": "tater-thirdreality-0.2.20",
                "artifacts": {
                    "factory": {
                        "path": "https://example.test/s420-factory.img",
                        "sha256": "a" * 64,
                        "size_bytes": 142_934_024,
                        "flash_transport": "amlogic_usb_burn",
                    },
                    "ota": {
                        "path": "https://example.test/s420-ota.swu",
                        "sha256": "b" * 64,
                        "size_bytes": 118_576_128,
                        "flash_transport": "tater_native_ota",
                    },
                },
            }
        ],
    }


class ThirdRealityFirmwareSupportTests(unittest.TestCase):
    def test_s420_manifest_is_normalized_for_verified_ota(self) -> None:
        source_url = "https://example.test/s420-manifest.json"
        normalized = _thirdreality_normalizer()(
            _thirdreality_manifest(),
            source_url=source_url,
        )
        device = normalized["devices"][0]

        self.assertEqual(device["key"], "thirdreality_s420")
        self.assertEqual(
            device["firmware_version"],
            "tater-thirdreality-0.2.20",
        )
        self.assertEqual(device["artifacts"]["ota"]["size_bytes"], 118_576_128)
        self.assertEqual(device["_source_url"], source_url)
        self.assertFalse(device["browser_usb_supported"])
        self.assertTrue(device["factory_install_external"])

    def test_s420_manifest_rejects_unverified_artifacts(self) -> None:
        manifest = _thirdreality_manifest()
        manifest["devices"][0]["artifacts"]["ota"]["sha256"] = "unverified"
        with self.assertRaisesRegex(ValueError, "artifact metadata is invalid"):
            _thirdreality_normalizer()(manifest)

    def test_catalog_fetches_thirdreality_as_an_independent_source(self) -> None:
        source = FIRMWARE_PATH.read_text(encoding="utf-8")

        self.assertIn("def _async_thirdreality_catalog", source)
        self.assertIn('source_names = ("native", "echo", "thirdreality")', source)
        self.assertIn("self._async_thirdreality_catalog()", source)

    def test_panel_explains_s420_factory_recovery_boundary(self) -> None:
        source = PANEL_PATH.read_text(encoding="utf-8")

        self.assertIn("ThirdReality S420 factory installation", source)
        self.assertIn("Tater Local USB with the debug board", source)


if __name__ == "__main__":
    unittest.main()
