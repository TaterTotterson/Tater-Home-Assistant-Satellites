from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_PATH = ROOT / "custom_components" / "tater_satellite" / "firmware.py"
CONST_PATH = ROOT / "custom_components" / "tater_satellite" / "const.py"
MANAGER_PATH = ROOT / "custom_components" / "tater_satellite" / "manager.py"
UPDATE_PATH = ROOT / "custom_components" / "tater_satellite" / "update.py"
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


def _echo_normalizer():
    module = ast.parse(FIRMWARE_PATH.read_text(encoding="utf-8"))
    names = {
        "_SHA256",
        "_VERSION",
        "board_manifest_key",
        "display_version",
        "normalize_echo_manifest",
    }
    selected = []
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in names
            for target in node.targets
        ):
            selected.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            selected.append(node)
    namespace = {
        "Any": Any,
        "Path": Path,
        "re": re,
        "BOARD_LABELS": _constant("BOARD_LABELS"),
        "BOARD_MANIFEST_KEYS": _constant("BOARD_MANIFEST_KEYS"),
        "ECHO_FIRMWARE_MANIFEST_URL": _constant("ECHO_FIRMWARE_MANIFEST_URL"),
        "ECHO_FIRMWARE_RELEASE_URL": _constant("ECHO_FIRMWARE_RELEASE_URL"),
    }
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(FIRMWARE_PATH), "exec"),
        namespace,
    )
    return namespace["normalize_echo_manifest"]


def _echo_manifest() -> dict[str, Any]:
    return {
        "schema": 1,
        "product": "Tater Echo Firmware",
        "version": "v0.2.0",
        "targets": {
            "biscuit": {
                "display_name": "Amazon Echo Dot 2nd Generation (2016)",
                "amazon_codename": "biscuit",
                "artifacts": {
                    "factory": {
                        "name": "tater-echo-biscuit-v0.2.0-factory.tar.gz",
                        "sha256": "a" * 64,
                        "size": 4096,
                    },
                    "ota": {
                        "name": "tater-echo-biscuit-v0.2.0-ota.bin",
                        "sha256": "b" * 64,
                        "size": 2048,
                    },
                },
            },
            "checkers": {
                "display_name": "Amazon Echo Show 5 1st Generation (2019)",
                "amazon_codename": "checkers",
                "artifacts": {
                    "factory": {
                        "name": "tater-echo-checkers-v0.2.0-factory.tar.gz",
                        "sha256": "c" * 64,
                        "size": 8192,
                    },
                    "ota": {
                        "name": "tater-echo-checkers-v0.2.0-ota.zip",
                        "sha256": "d" * 64,
                        "size": 6144,
                    },
                },
            },
        },
    }


class EchoFirmwareSupportTests(unittest.TestCase):
    def test_combined_echo_manifest_normalizes_both_ota_targets(self) -> None:
        source_url = _constant("ECHO_FIRMWARE_MANIFEST_URL")
        normalized = _echo_normalizer()(_echo_manifest(), source_url=source_url)
        devices = {row["key"]: row for row in normalized["devices"]}

        self.assertEqual(set(devices), {"biscuit", "checkers"})
        self.assertEqual(devices["biscuit"]["firmware_version"], "v0.2.0")
        self.assertEqual(
            devices["checkers"]["artifacts"]["ota"]["path"],
            "tater-echo-checkers-v0.2.0-ota.zip",
        )
        self.assertEqual(
            devices["checkers"]["artifacts"]["ota"]["size_bytes"],
            6144,
        )
        self.assertFalse(devices["biscuit"]["browser_usb_supported"])
        self.assertFalse(devices["checkers"]["browser_usb_supported"])
        self.assertEqual(devices["checkers"]["_source_url"], source_url)

    def test_echo_manifest_rejects_unverified_artifact_metadata(self) -> None:
        manifest = _echo_manifest()
        manifest["targets"]["checkers"]["artifacts"]["ota"]["sha256"] = "unverified"
        with self.assertRaisesRegex(ValueError, "artifact metadata is invalid"):
            _echo_normalizer()(manifest)

    def test_ota_command_includes_integrity_metadata(self) -> None:
        source = MANAGER_PATH.read_text(encoding="utf-8")

        self.assertIn('target = runtime.firmware_catalog_target', source)
        self.assertIn('"sha256": signed.sha256', source)
        self.assertIn('"size_bytes": signed.size_bytes', source)

    def test_echo_release_page_and_factory_boundary_are_exposed(self) -> None:
        update_source = UPDATE_PATH.read_text(encoding="utf-8")
        panel_source = PANEL_PATH.read_text(encoding="utf-8")

        self.assertIn("def release_url", update_source)
        self.assertIn("self.runtime.firmware_catalog_target", update_source)
        self.assertIn("row.browser_usb_supported !== false", panel_source)
        self.assertIn("model-specific Echo factory installers", panel_source)


if __name__ == "__main__":
    unittest.main()
